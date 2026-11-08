import { useEffect, useState, type KeyboardEvent as KeyEvent } from "react";
import { api, type Doc, type DocEntry, type DocField, type Library, type Told } from "../api";
import { Icon } from "./icons";

/** Where the Documents page is: the list, one document, or what one person told Sahl ("0": told before anyone). */
export type DocView = { doc: string } | { told: string } | null;

type Props = {
  t: (k: string, vars?: Record<string, string | number>) => string;
  view: DocView;
  setView: (v: DocView) => void;
  busy: boolean;
  library: string | null; // the documents folder, already shortened for showing
  onAdd: () => void;
  onChangeFolder: () => void;
  onForgetAll: () => void;
  confirm: (text: string) => Promise<boolean>;
  fail: (e: unknown) => void;
  reload: number; // bumped after documents are added or everything is forgotten
};

const TYPE_ICON = { passport: "passport", eid: "card", other: "docs" } as const;

/** One value: shown, or edited in place. Enter saves, Escape puts it back. */
function Value({ label, value, status, note, onSave, onUndo, t }: {
  label: string; value: string; status: "checked" | "check" | "edited" | "told"; note?: string;
  onSave: (v: string) => Promise<void>; onUndo?: () => void; t: Props["t"];
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (draft === null || !draft.trim() || draft.trim() === value) return setDraft(null);
    setSaving(true);
    try {
      await onSave(draft.trim());
      setDraft(null);
    } finally {
      setSaving(false);
    }
  };
  const key = (e: KeyEvent) => {
    if (e.key === "Escape") e.preventDefault(), e.stopPropagation(), setDraft(null);
  };
  return (
    <div className="row stacked value-row">
      <div className="value-head">
        <span className="value-label" dir="auto">{label}</span>
        <span className={`status ${status}`}>{t(`status_${status}`)}</span>
      </div>
      {draft === null ? (
        <div className="value">
          <code dir="ltr">{value}</code>
          <button className="ghost icon-text" onClick={() => setDraft(value)} aria-label={`${t("edit")} ${label}`}>
            <Icon name="pencil" />{t("edit")}
          </button>
        </div>
      ) : (
        <form className="edit" onSubmit={(e) => (e.preventDefault(), void save())}>
          <input value={draft} autoFocus dir="auto" aria-label={label} onKeyDown={key} onFocus={(e) => e.target.select()} onChange={(e) => setDraft(e.target.value)} />
          <button className="primary" type="submit" disabled={saving || !draft.trim()}>{t("save")}</button>
          <button className="link" type="button" onClick={() => setDraft(null)}>{t("cancel")}</button>
        </form>
      )}
      {note && <p className="fine" dir="auto">{note}</p>}
      {onUndo && draft === null && <button className="link start" onClick={onUndo}>{t("undo_edit")}</button>}
    </div>
  );
}

export default function Documents({ t, view, setView, busy, library, onAdd, onChangeFolder, onForgetAll, confirm, fail, reload }: Props) {
  const [lib, setLib] = useState<Library | null>(null);
  useEffect(() => void api<Library>("/vault/documents").then(setLib).catch(fail), [reload]);
  // a document or a person that was just removed: back to the list
  useEffect(() => {
    if (!lib || !view) return;
    if ("doc" in view && !lib.documents.some((d) => d.path === view.doc)) setView(null);
    if ("told" in view && !lib.told.some((x) => x.person === view.told)) setView(null);
  }, [lib, view]);

  const name = (person: string | null) => lib?.people.find((p) => p.id === person)?.name ?? t("docs_nobody");
  const docType = (d: Doc) => t(`doctitle_${d}`);
  const fieldName = (f: DocField) => {
    const s = t(`key_${f.key}`) as string | undefined; // a kind of value this version has no name for: its key
    return s || f.key;
  };
  const toCheck = (d: DocEntry) => d.fields.filter((f) => !f.verified).length;
  const post = (path: string, body: object) => api<Library>(path, body).then(setLib).catch((e) => (fail(e), Promise.reject(e)));

  if (!lib) return <p className="fine" role="status">…</p>;

  // --- one document: what was read, each value editable ---
  if (view && "doc" in view) {
    const d = lib.documents.find((x) => x.path === view.doc);
    if (!d) return null;
    return (
      <>
        <div className="doc-head">
          <span className={`tile doc ${d.type}`}><Icon name={TYPE_ICON[d.type]} /></span>
          <div>
            <h3>{docType(d.type)} · <bdi>{name(d.person)}</bdi></h3>
            <p className="fine path" dir="ltr" title={d.file}>{d.file}</p>
          </div>
        </div>
        {d.fields.length ? (
          <section className="group" aria-label={docType(d.type)}>
            {d.fields.map((f) => (
              <Value key={f.id} t={t} label={fieldName(f)} value={f.value}
                status={f.edited ? "edited" : f.verified ? "checked" : "check"}
                note={f.edited ? t("read_as", { value: f.read }) : undefined}
                onSave={(v) => post("/vault/correct", { path: d.path, key: f.id, value: v })}
                onUndo={f.edited ? () => void post("/vault/correct", { path: d.path, key: f.id, value: null }).catch(() => {}) : undefined} />
            ))}
          </section>
        ) : (
          <p className="page-text">{t("doc_nothing_read")}</p>
        )}
        <p className="fine">{t("docs_explain")}</p>
        <section className="group">
          <button className="row danger-row" disabled={busy}
            onClick={async () => (await confirm(t("remove_doc_ask", { doc: t(`doc_${d.type}`) }))) && void post("/vault/remove", { path: d.path }).catch(() => {})}>
            <Icon name="trash" />{t("remove_doc")}
          </button>
        </section>
      </>
    );
  }

  // --- what one person told Sahl about boxes no guide knows ---
  if (view && "told" in view) {
    const told = lib.told.filter((x) => x.person === view.told);
    const change = (x: Told, value: string) =>
      api("/taught/change", { concept: x.concept, value, person: x.person }).then(() => api<Library>("/vault/documents")).then(setLib)
        .catch((e) => (fail(e), Promise.reject(e)));
    return (
      <>
        <h3 className="doc-title">{t("docs_told")} · <bdi>{name(view.told === "0" ? null : view.told)}</bdi></h3>
        <section className="group" aria-label={t("docs_told")}>
          {told.map((x) => (
            <div key={x.concept}>
              <Value t={t} label={x.concept} value={x.value} status="told"
                note={x.labels.length > 1 ? t("told_also", { labels: x.labels.join(", ") }) : undefined}
                onSave={(v) => change(x, v)} />
              <button className="link start remove" onClick={async () => {
                if (!(await confirm(t("remove_told_ask", { concept: x.concept })))) return;
                await api("/taught/forget", { concept: x.concept, person: x.person }).catch(fail);
                setLib(await api<Library>("/vault/documents"));
              }}>{t("remove")}</button>
            </div>
          ))}
        </section>
      </>
    );
  }

  // --- the list: each person's documents, then what they told Sahl ---
  const owners = [...lib.people.map((p) => p.id), null];
  const groups = owners
    .map((id) => ({ id, docs: lib.documents.filter((d) => d.person === id), told: lib.told.filter((x) => x.person === (id ?? "0")) }))
    .filter((g) => g.docs.length || g.told.length);
  return (
    <>
      <div className="docs-top">
        <button className="primary" disabled={busy} onClick={onAdd}><Icon name="plus" />{t("add_doc")}</button>
      </div>
      {!groups.length && (
        <div className="empty">
          <p className="page-text">{t("no_docs")}</p>
        </div>
      )}
      {groups.map((g) => (
        <section key={g.id ?? "none"} aria-label={name(g.id)}>
          <h3 className="group-title"><bdi>{name(g.id)}</bdi></h3>
          <div className="group">
            {g.docs.map((d) => {
              const n = toCheck(d);
              return (
                <button key={d.path} className="row nav" onClick={() => setView({ doc: d.path })}>
                  <span className="label">
                    <span className={`tile doc ${d.type}`}><Icon name={TYPE_ICON[d.type]} /></span>
                    <span className="two">
                      <span>{docType(d.type)}</span>
                      <span className="fine" dir="ltr">{d.file}</span>
                    </span>
                  </span>
                  {d.fields.length
                    ? <span className={n ? "status check" : "status checked"}>{n ? t("docs_check", { n }) : t("docs_all_checked")}</span>
                    : <span className="status none">{t("docs_nothing")}</span>}
                  <span className="chevron" aria-hidden />
                </button>
              );
            })}
            {!!g.told.length && (
              <button className="row nav" onClick={() => setView({ told: g.id ?? "0" })}>
                <span className="label">
                  <span className="tile doc told"><Icon name="chat" /></span>
                  <span>{t("docs_told")}</span>
                </span>
                <span className="held">{g.told.length}</span>
                <span className="chevron" aria-hidden />
              </button>
            )}
          </div>
        </section>
      ))}
      <section className="group" aria-label={t("docs_folder")}>
        {library && (
          <div className="row">
            <span className="label"><Icon name="folder" /><span className="path" dir="ltr" title={library}>{library}</span></span>
            <button className="ghost" disabled={busy} onClick={onChangeFolder}>{t("change")}</button>
          </div>
        )}
        <button className="row danger-row" disabled={busy} onClick={onForgetAll}><Icon name="trash" />{t("forget")}</button>
      </section>
      <p className="fine">{t("docs_drop")}</p>
    </>
  );
}
