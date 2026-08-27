import marimo

__generated_with = "0.23.6"
app = marimo.App(width="medium", app_title="MagnetDB Assembly Explorer")


@app.cell
def _():
    from pathlib import Path

    import duckdb
    import marimo as mo
    import pandas as pd

    return Path, duckdb, mo, pd


@app.cell
def _(Path, mo):
    db_input = mo.ui.text(
        value=str(Path(__file__).parent / ".." / "magnetdb.duckdb"),
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
        _assemblies = _con.execute(
            "SELECT name, housing, status, commissioned_at, decommissioned_at "
            "FROM assemblies ORDER BY name"
        ).fetchall()
        _con.close()
        db_error = None
        assembly_rows = _assemblies
    except Exception as _e:
        db_error = str(_e)
        assembly_rows = []

    if db_error:
        mo.stop(
            True,
            mo.callout(mo.md(f"**Cannot open database:** {db_error}"), kind="danger"),
        )
    return db_error, db_path, assembly_rows


@app.cell
def _(mo, assembly_rows):
    assembly_names = [r[0] for r in assembly_rows]
    assembly_selector = mo.ui.dropdown(
        options=assembly_names,
        value=assembly_names[0] if assembly_names else None,
        label="Select assembly",
    )
    mo.md(f"## Assembly selection\n{assembly_selector}")
    return assembly_names, assembly_selector


@app.cell
def _(db_path, duckdb, mo, pd, assembly_selector):
    selected = assembly_selector.value
    mo.stop(selected is None, mo.callout(mo.md("No assembly selected."), kind="warn"))

    con = duckdb.connect(db_path, read_only=True)

    # --- Assembly metadata ---
    assembly_row = con.execute(
        "SELECT name, housing, status, commissioned_at, decommissioned_at "
        "FROM assemblies WHERE name = ?",
        [selected],
    ).fetchone()

    # --- Magnets in this assembly ---
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
        FROM assembly_magnets sm
        JOIN magnets m ON m.name = sm.magnet_name
        WHERE sm.assembly_name = ?
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
        FROM assembly_magnets sm
        JOIN magnets m       ON m.name         = sm.magnet_name
        JOIN magnet_parts mp ON mp.magnet_name = m.name
        JOIN parts p         ON p.name         = mp.part_name
        LEFT JOIN materials mat ON mat.name    = p.material_name
        WHERE sm.assembly_name = ?
        ORDER BY m.name, mp.rank
        """,
        [selected],
    ).df()

    # --- Experiments with duration ---
    exp_df = con.execute(
        """
        SELECT
            e.id,
            e.name,
            e.file,
            e.status,
            ers.value AS duration_s
        FROM experiments e
        LEFT JOIN exp_run_scalars ers
            ON ers.experiment_id = e.id AND ers.channel = 'duration_s'
        WHERE e.assembly_name = ?
        ORDER BY e.file
        """,
        [selected],
    ).df()

    con.close()

    def _fmt_duration(seconds):
        if seconds is None or (hasattr(seconds, '__class__') and seconds != seconds):
            return "—"
        s = int(seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}h {m:02d}m {sec:02d}s"
        return f"{m}m {sec:02d}s"

    exp_df["duration"] = exp_df["duration_s"].apply(_fmt_duration)
    exp_df = exp_df.drop(columns=["duration_s"])

    # ── Display ──────────────────────────────────────────────────────────────
    name, housing, status, comm_at, decomm_at = assembly_row
    decomm_str = str(decomm_at) if decomm_at else "—"

    summary = mo.md(f"""
## Assembly: `{name}`

| Field | Value |
|-------|-------|
| Housing | **{housing or '—'}** |
| Status  | **{status or '—'}** |
| Commissioned   | {comm_at} |
| Decommissioned | {decomm_str} |
| Magnets    | {len(magnets_df)} |
| Experiments | {len(exp_df)} |
""")

    magnets_section = mo.vstack(
        [
            mo.md("### Magnets"),
            mo.ui.table(magnets_df, selection=None),
        ]
    )

    hierarchy_section = mo.vstack(
        [
            mo.md("### Parts hierarchy"),
            mo.ui.table(hierarchy_df, selection=None),
        ]
    )

    exp_section = mo.vstack(
        [
            mo.md(f"### Experiments ({len(exp_df)})"),
            (
                mo.ui.table(exp_df, selection=None)
                if not exp_df.empty
                else mo.callout(
                    mo.md("No experiments registered for this assembly."), kind="info"
                )
            ),
        ]
    )

    mo.vstack([summary, magnets_section, hierarchy_section, exp_section])
