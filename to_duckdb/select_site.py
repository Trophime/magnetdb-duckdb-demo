import marimo

__generated_with = "0.23.6"
app = marimo.App(width="medium", app_title="MagnetDB Site Explorer")


@app.cell
def _():
    import marimo as mo
    import duckdb
    import pandas as pd
    from pathlib import Path
    return Path, duckdb, mo, pd


@app.cell
def _(Path, mo):
    db_input = mo.ui.text(
        value=str(Path(__file__).parent / "student_magnetdb-2604.duckdb"),
        label="DuckDB file",
        full_width=True,
    )
    mo.md(f"## Database\n{db_input}")
    return (db_input,)


@app.cell
def _(db_input, duckdb, mo):
    db_path = db_input.value.strip()
    try:
        _con = duckdb.connect(db_path, read_only=True)
        _sites = _con.execute(
            "SELECT name, housing, status, commissioned_at, decommissioned_at "
            "FROM sites ORDER BY name"
        ).fetchall()
        _con.close()
        db_error = None
        site_rows = _sites
    except Exception as _e:
        db_error = str(_e)
        site_rows = []

    if db_error:
        mo.stop(True, mo.callout(mo.md(f"**Cannot open database:** {db_error}"), kind="danger"))
    return db_error, db_path, site_rows


@app.cell
def _(mo, site_rows):
    site_names = [r[0] for r in site_rows]
    site_selector = mo.ui.dropdown(
        options=site_names,
        value=site_names[0] if site_names else None,
        label="Select site",
    )
    mo.md(f"## Site selection\n{site_selector}")
    return site_names, site_selector


@app.cell
def _(db_path, duckdb, mo, pd, site_selector):
    selected = site_selector.value
    mo.stop(selected is None, mo.callout(mo.md("No site selected."), kind="warn"))

    con = duckdb.connect(db_path, read_only=True)

    # --- Site metadata ---
    site_row = con.execute(
        "SELECT name, housing, status, commissioned_at, decommissioned_at "
        "FROM sites WHERE name = ?",
        [selected],
    ).fetchone()

    # --- Magnets in this site ---
    magnets_df = con.execute(
        """
        SELECT
            sm.magnet_name          AS magnet,
            m.type                  AS type,
            m.status                AS status,
            sm.z_offset,
            sm.r_offset,
            sm.commissioned_at      AS commissioned,
            sm.decommissioned_at    AS decommissioned
        FROM site_magnets sm
        JOIN magnets m ON m.name = sm.magnet_name
        WHERE sm.site_name = ?
        ORDER BY sm.magnet_name
        """,
        [selected],
    ).df()

    # --- Parts hierarchy ---
    hierarchy_df = con.execute(
        """
        SELECT
            m.name          AS magnet,
            m.type          AS magnet_type,
            mp.coil_index,
            mp.rank,
            p.name          AS part,
            p.type          AS part_type,
            mat.nuance,
            ROUND(mat.rpe / 1e6, 1) AS rpe_MPa
        FROM site_magnets sm
        JOIN magnets m       ON m.name         = sm.magnet_name
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts p         ON p.name         = mp.part_name
        LEFT JOIN materials mat ON mat.name    = p.material_name
        WHERE sm.site_name = ?
        ORDER BY m.name, mp.rank
        """,
        [selected],
    ).df()

    # --- Experiments ---
    exp_df = con.execute(
        """
        SELECT id, name, file, status
        FROM experiments
        WHERE site_name = ?
        ORDER BY file
        """,
        [selected],
    ).df()

    con.close()

    # ── Display ──────────────────────────────────────────────────────────────
    name, housing, status, comm_at, decomm_at = site_row
    decomm_str = str(decomm_at) if decomm_at else "—"

    summary = mo.md(f"""
## Site: `{name}`

| Field | Value |
|-------|-------|
| Housing | **{housing or '—'}** |
| Status  | **{status or '—'}** |
| Commissioned   | {comm_at} |
| Decommissioned | {decomm_str} |
| Magnets    | {len(magnets_df)} |
| Experiments | {len(exp_df)} |
""")

    magnets_section = mo.vstack([
        mo.md("### Magnets"),
        mo.ui.table(magnets_df, selection=None),
    ])

    hierarchy_section = mo.vstack([
        mo.md("### Parts hierarchy"),
        mo.ui.table(hierarchy_df, selection=None),
    ])

    exp_section = mo.vstack([
        mo.md(f"### Experiments ({len(exp_df)})"),
        mo.ui.table(exp_df, selection=None) if not exp_df.empty
        else mo.callout(mo.md("No experiments registered for this site."), kind="info"),
    ])

    mo.vstack([summary, magnets_section, hierarchy_section, exp_section])
