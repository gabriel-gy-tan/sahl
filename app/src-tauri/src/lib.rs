use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

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
        let mut child = Command::new(root.join(".venv/bin/python"))
            .args(["-m", "sahl.server"])
            .current_dir(&root)
            .env("SAHL_TOKEN", &s.token)
            .stdout(Stdio::piped())
            .spawn()
            .expect("could not start sidecar/.venv/bin/python, see sidecar/README.md");
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcuts(["alt+space"])
                .expect("shortcut")
                .with_handler(|app, _, ev| {
                    if ev.state == ShortcutState::Pressed {
                        let _ = app.emit_to("panel", "read", ());
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![sidecar_info])
        .setup(|app| {
            spawn_sidecar(app.handle());
            let mon = app.primary_monitor()?.expect("a monitor");
            let scale = mon.scale_factor();
            let size = mon.size().to_logical::<f64>(scale);
            let pos = mon.position().to_logical::<f64>(scale);

            let panel = app.get_webview_window("panel").unwrap();
            panel.set_position(tauri::LogicalPosition::new(pos.x + size.width - 400.0, pos.y + 80.0))?;
            #[cfg(target_os = "macos")]
            window_vibrancy::apply_vibrancy(&panel, window_vibrancy::NSVisualEffectMaterial::HudWindow, None, Some(16.0))?;

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
