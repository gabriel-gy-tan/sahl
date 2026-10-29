use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::ShortcutState;

struct Sidecar {
    port: Mutex<Option<u16>>,
    token: String,
    child: Mutex<Option<Child>>,
    exiting: AtomicBool,
}

#[derive(serde::Serialize)]
struct Info {
    port: Option<u16>,
    token: String,
}

/// Where the island hangs: the top centre of one screen, in logical points.
#[derive(serde::Serialize, Clone, Copy)]
struct Notch {
    /// a real camera notch, rather than a black tab drawn over the menu bar
    real: bool,
    width: f64,
    height: f64,
    #[serde(skip)]
    screen_x: f64,
    #[serde(skip)]
    screen_y: f64,
    #[serde(skip)]
    screen_width: f64,
    /// height of the primary screen: AppKit window frames count y up from its bottom
    #[serde(skip)]
    primary_height: f64,
}

/// The island on one screen of a Mac: under its notch, or a notch-sized tab over the menu bar where there is none.
#[cfg(target_os = "macos")]
fn screen_notch(s: &objc2_app_kit::NSScreen, primary_height: f64) -> Notch {
    let f = s.frame();
    // SAHL_NO_NOTCH=1 shows the tab Sahl draws on screens without a notch, to try it on a notched Mac
    let real = s.safeAreaInsets().top > 0.0 && std::env::var_os("SAHL_NO_NOTCH").is_none();
    let (left, right) = (s.auxiliaryTopLeftArea(), s.auxiliaryTopRightArea());
    let menu_bar = f.origin.y + f.size.height - (s.visibleFrame().origin.y + s.visibleFrame().size.height);
    Notch {
        real,
        width: if real { f.size.width - left.size.width - right.size.width } else { 190.0 },
        height: if real { s.safeAreaInsets().top } else { menu_bar.max(24.0) },
        screen_x: f.origin.x,
        screen_y: primary_height - (f.origin.y + f.size.height), // AppKit counts y up from the primary screen's bottom
        screen_width: f.size.width,
        primary_height,
    }
}

/// Every screen's island, as connected now.
#[cfg(target_os = "macos")]
fn mac_screens(mtm: objc2::MainThreadMarker) -> Vec<Notch> {
    let screens = objc2_app_kit::NSScreen::screens(mtm);
    let top = screens.firstObject().map(|s| s.frame().size.height).unwrap_or(0.0);
    screens.iter().map(|s| screen_notch(&s, top)).collect()
}

/// Where the island starts: the built-in notch if there is one, otherwise the main screen's tab.
fn find_notch(app: &tauri::App) -> tauri::Result<Notch> {
    #[cfg(target_os = "macos")]
    {
        let screens = mac_screens(objc2::MainThreadMarker::new().expect("setup runs on the main thread"));
        if let Some(n) = screens.iter().find(|n| n.real).or(screens.first()) {
            return Ok(*n);
        }
    }
    // ponytail: Windows stays on the primary monitor; follow the pointer there too once it's tested on Windows
    let mon = app.primary_monitor()?.expect("a monitor");
    let size = mon.size().to_logical::<f64>(mon.scale_factor());
    let pos = mon.position().to_logical::<f64>(mon.scale_factor());
    Ok(Notch { real: false, width: 190.0, height: 8.0, screen_x: pos.x, screen_y: pos.y, screen_width: size.width, primary_height: 0.0 })
}

/// The screen the island is on now. It moves to another screen when the pointer reaches that screen's top centre.
struct Active(Mutex<Notch>);

#[tauri::command]
fn notch(active: tauri::State<Active>) -> Notch {
    *active.0.lock().unwrap()
}

/// The island's own size inside the panel window, in points, and whether it is open: hover is measured
/// against it, not the window, and it only moves to another screen while folded.
struct Hit(Mutex<(f64, f64, bool)>);

/// Sizes the panel window under the notch and records the island's size for hover.
///
/// The window keeps one width and only its height changes: a window that grows sideways shows its old picture
/// pinned to the new left edge for a moment, which made the island jump. Folded, the window lets clicks through,
/// so its empty sides never block the menu bar.
#[tauri::command]
fn island(window: tauri::WebviewWindow, active: tauri::State<Active>, hit: tauri::State<Hit>, width: f64, height: f64,
          island_width: f64, island_height: f64, open: bool) -> tauri::Result<()> {
    *hit.0.lock().unwrap() = (island_width, island_height, open);
    let n = *active.0.lock().unwrap();
    window.set_ignore_cursor_events(!open)?;
    // the window starts hidden (tauri.conf.json) so the first frame isn't drawn at the wrong size; show it once sized
    let first = !window.is_visible()?;
    let x = n.screen_x + (n.screen_width - width) / 2.0;
    #[cfg(target_os = "macos")]
    {
        use objc2_app_kit::NSWindow;
        use objc2_foundation::{NSPoint, NSRect, NSSize};
        let ns = window.ns_window()? as usize;
        let y = n.primary_height - n.screen_y - height; // AppKit frames grow up from the bottom; keep the top edge put
        return window.run_on_main_thread(move || {
            let ns = unsafe { &*(ns as *const NSWindow) };
            ns.setFrame_display(NSRect::new(NSPoint::new(x, y), NSSize::new(width, height)), true);
            if first {
                ns.orderFrontRegardless(); // shown without taking focus from the app in front
            }
        });
    }
    // one call on Windows too: separate size and position calls show a frame at the old place
    // ponytail: untested on Windows (no Windows build here)
    #[cfg(windows)]
    {
        use windows::Win32::UI::WindowsAndMessaging::{SetWindowPos, SWP_NOACTIVATE, SWP_NOZORDER};
        let s = window.scale_factor()?; // SetWindowPos takes physical pixels
        let px = |v: f64| (v * s).round() as i32;
        unsafe { SetWindowPos(window.hwnd()?, None, px(x), px(n.screen_y), px(width), px(height), SWP_NOZORDER | SWP_NOACTIVATE) }
            .map_err(|e| tauri::Error::Anyhow(e.into()))?;
        if first {
            window.show()?;
        }
        return Ok(());
    }
    #[cfg(not(any(target_os = "macos", windows)))]
    {
        window.set_size(tauri::LogicalSize::new(width, height))?;
        window.set_position(tauri::LogicalPosition::new(x, n.screen_y))?;
        if first {
            window.show()?;
        }
        Ok(())
    }
}

/// Starts the system's own dictation in the focused text box: Start Dictation on macOS, Voice Typing (Win+H) on Windows.
/// The OS does the listening and types the words in; Sahl never handles audio.
#[tauri::command]
fn dictate(window: tauri::WebviewWindow) -> tauri::Result<()> {
    window.set_focus()?; // dictation types into the key window's focused box
    #[cfg(target_os = "macos")]
    return window.run_on_main_thread(|| {
        use objc2::{sel, MainThreadMarker};
        use objc2_app_kit::NSApplication;
        let app = NSApplication::sharedApplication(MainThreadMarker::new().expect("main thread"));
        unsafe { app.sendAction_to_from(sel!(startDictation:), None, None) };
    });
    // ponytail: untested on Windows (no Windows build here); check Win+H opens Voice Typing in the island
    #[cfg(windows)]
    {
        use windows::Win32::UI::Input::KeyboardAndMouse::*;
        let key = |vk: u16, up: bool| INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT { wVk: VIRTUAL_KEY(vk), dwFlags: if up { KEYEVENTF_KEYUP } else { KEYBD_EVENT_FLAGS(0) }, ..Default::default() },
            },
        };
        let h = 0x48; // the H key
        let keys = [key(VK_LWIN.0, false), key(h, false), key(h, true), key(VK_LWIN.0, true)];
        unsafe { SendInput(&keys, std::mem::size_of::<INPUT>() as i32) };
        Ok(())
    }
    #[cfg(not(any(target_os = "macos", windows)))]
    Ok(())
}

/// Tells the panel when the pointer enters or leaves it. A webview in a window that isn't
/// focused gets no hover events on macOS, and the island must open without a click.
fn watch_hover(app: &tauri::AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        let was = std::sync::Arc::new(AtomicBool::new(false));
        loop {
            std::thread::sleep(std::time::Duration::from_millis(50));
            let (app2, was) = (app.clone(), was.clone());
            // AppKit's screens and pointer are read on the main thread; they are exact across screens of any scale
            #[cfg(target_os = "macos")]
            let _ = app.run_on_main_thread(move || {
                let Some(mtm) = objc2::MainThreadMarker::new() else { return };
                let screens = mac_screens(mtm);
                let m = objc2_app_kit::NSEvent::mouseLocation();
                let top = screens.first().map(|s| s.primary_height).unwrap_or(0.0);
                hover_tick(&app2, &was, &screens, m.x, top - m.y);
            });
            #[cfg(not(target_os = "macos"))]
            {
                let Some(w) = app.get_webview_window("panel") else { continue };
                let (Ok(c), Ok(scale)) = (app.cursor_position(), w.scale_factor()) else { continue };
                hover_tick(&app2, &was, &[], c.x / scale, c.y / scale);
            }
        }
    });
}

/// One look at the pointer (top-left screen points): move the folded island to the screen whose top centre the
/// pointer reached, and say when it enters or leaves the island.
fn hover_tick(app: &tauri::AppHandle, was: &AtomicBool, screens: &[Notch], cx: f64, cy: f64) {
    let (iw, ih, open) = *app.state::<Hit>().0.lock().unwrap();
    let active = app.state::<Active>();
    let mut n = *active.0.lock().unwrap();
    let centre = |s: &Notch| s.screen_x + s.screen_width / 2.0;
    if !open {
        let elsewhere = |s: &&Notch| (s.screen_x, s.screen_y) != (n.screen_x, n.screen_y);
        let at_top = |s: &&Notch| (cx - centre(s)).abs() < s.width / 2.0 + 40.0 && cy >= s.screen_y && cy < s.screen_y + s.height;
        if let Some(s) = screens.iter().filter(elsewhere).find(at_top) {
            n = *s;
            *active.0.lock().unwrap() = n;
            let _ = app.emit_to("panel", "notch", n); // the panel resizes for this screen's notch, which moves the window
        }
    }
    let inside = (cx - centre(&n)).abs() < iw / 2.0 && cy >= n.screen_y && cy < n.screen_y + ih;
    if inside != was.swap(inside, Ordering::SeqCst) {
        let _ = app.emit_to("panel", "hover", inside);
    }
}

#[tauri::command]
fn sidecar_info(s: tauri::State<Sidecar>) -> Info {
    Info { port: *s.port.lock().unwrap(), token: s.token.clone() }
}

/// Starts the Python sidecar (OCR, vault, typing) on a random local port with a fresh token,
/// and starts it again whenever it dies, so the panel never talks to a dead process.
fn spawn_sidecar(app: &tauri::AppHandle) {
    let mut buf = [0u8; 24];
    getrandom::fill(&mut buf).expect("os randomness");
    let token: String = buf.iter().map(|b| format!("{b:02x}")).collect();
    app.manage(Sidecar { port: Mutex::new(None), token, child: Mutex::new(None), exiting: AtomicBool::new(false) });
    let handle = app.clone();
    std::thread::spawn(move || loop {
        // ponytail: dev layout only (repo checkout with sidecar/.venv); bundle the sidecar for releases
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../sidecar");
        let s = handle.state::<Sidecar>();
        let python = if cfg!(windows) {
            root.join(".venv/Scripts/python.exe")
        } else {
            root.join(".venv/bin/python")
        };
        let mut cmd = Command::new(&python);
        cmd.args(["-m", "sahl.server"])
            .current_dir(&root)
            .env("SAHL_TOKEN", &s.token)
            .stdout(Stdio::piped());
        #[cfg(windows)]
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashes up beside the panel
        let mut child = cmd
            .spawn()
            .unwrap_or_else(|e| panic!("could not start {} ({e}), see sidecar/README.md", python.display()));
        let out = child.stdout.take().unwrap();
        *s.child.lock().unwrap() = Some(child);
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            if let Some(p) = line.strip_prefix("SAHL_PORT=") {
                *s.port.lock().unwrap() = p.trim().parse().ok();
            } else {
                println!("sidecar: {line}");
            }
        }
        // stdout closed: the sidecar has exited
        *s.port.lock().unwrap() = None;
        let status = s.child.lock().unwrap().take().map(|mut c| c.wait());
        if s.exiting.load(Ordering::SeqCst) {
            return;
        }
        eprintln!("sahl: sidecar exited ({status:?}), restarting");
        std::thread::sleep(std::time::Duration::from_secs(1));
    });
}

/// Reads the form on screen. Alt+Space is the window menu on Windows, so it gets Ctrl+Alt+Space there.
const SHORTCUT: &str = if cfg!(target_os = "macos") { "alt+space" } else { "ctrl+alt+space" };

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcuts([SHORTCUT])
                .expect("shortcut")
                .with_handler(|app, _, ev| {
                    if ev.state == ShortcutState::Pressed {
                        let _ = app.emit_to("panel", "read", ());
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![sidecar_info, notch, island, dictate])
        .setup(|app| {
            spawn_sidecar(app.handle());
            let mon = app.primary_monitor()?.expect("a monitor");
            let scale = mon.scale_factor();
            let size = mon.size().to_logical::<f64>(scale);
            let pos = mon.position().to_logical::<f64>(scale);

            // the panel is a black island hanging from the notch, above the menu bar, on every Space
            let n = find_notch(app)?;
            app.manage(Active(Mutex::new(n)));
            app.manage(Hit(Mutex::new((n.width, n.height, false))));
            let panel = app.get_webview_window("panel").unwrap();
            panel.set_size(tauri::LogicalSize::new(n.width, n.height))?;
            panel.set_position(tauri::LogicalPosition::new(n.screen_x + (n.screen_width - n.width) / 2.0, n.screen_y))?;
            #[cfg(target_os = "macos")]
            {
                use objc2_app_kit::{NSWindow, NSWindowCollectionBehavior as B};
                let ns = unsafe { &*(panel.ns_window()? as *const NSWindow) };
                ns.setLevel(25); // NSStatusWindowLevel: above the menu bar
                ns.setCollectionBehavior(B::CanJoinAllSpaces | B::Stationary | B::FullScreenAuxiliary | B::IgnoresCycle);
            }
            watch_hover(app.handle());

            // full-screen, click-through layer that draws the ring around the next box
            let overlay = WebviewWindowBuilder::new(app, "overlay", WebviewUrl::App("index.html".into()))
                .transparent(true)
                .decorations(false)
                .shadow(false)
                .always_on_top(true)
                .skip_taskbar(true)
                .resizable(false)
                .focused(false)
                .visible(false)
                .position(pos.x, pos.y)
                .inner_size(size.width, size.height)
                .build()?;
            overlay.set_ignore_cursor_events(true)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Sahl")
        .run(|app, ev| match ev {
            // logged so an unexpected quit says why
            RunEvent::ExitRequested { code, .. } => eprintln!("sahl: exit requested (code {code:?})"),
            RunEvent::WindowEvent { label, event: tauri::WindowEvent::Destroyed, .. } => eprintln!("sahl: window {label} closed"),
            RunEvent::Exit => {
                eprintln!("sahl: exiting");
                let s = app.state::<Sidecar>();
                s.exiting.store(true, Ordering::SeqCst);
                if let Some(mut c) = s.child.lock().unwrap().take() {
                    let _ = c.kill();
                }
            }
            _ => {}
        });
}
