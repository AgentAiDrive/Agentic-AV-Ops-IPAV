# sma-av-streamlit/pages/7_🧩_Workflows.py
from __future__ import annotations

from datetime import datetime

import streamlit as st
from core.db.session import get_session
from core.db.seed import init_db
from core.db.models import Agent, Recipe
from core.workflow.service import (
    list_workflows, create_workflow, update_workflow, delete_workflow,
    run_now, compute_status, tick
)
from core.ui.page_tips import show as show_tip
from core.io.port import export_zip, import_zip

PAGE_KEY = "Workflows"
show_tip(PAGE_KEY)

st.title("🧩 Workflows")
init_db()

with get_session() as db:  # keep DB open for the whole page render
    wfs = list_workflows(db)
    existing_names = {wf.name.lower(): wf.id for wf in wfs}

    colL, colR = st.columns([1, 3])
    if colL.button("⏱️ Tick scheduler"):
        n = tick(db)
        st.toast(f"Ticked. Ran {n} workflow(s).")

    # --- New Workflow (ID-based, avoid ORM instances in widget state) ---
    st.subheader("New Workflow")

    agent_opts = {a.id: a.name for a in db.query(Agent).order_by(Agent.name).all()}
    recipe_opts = {r.id: r.name for r in db.query(Recipe).order_by(Recipe.name).all()}

    with st.form("new_wf"):
        name = st.text_input("Name", help="Workflow names must be unique (case-insensitive).")

        agent_id = (
            st.selectbox(
                "Agent",
                options=list(agent_opts.keys()),
                format_func=lambda i: agent_opts[i],
            ) if agent_opts else None
        )

        recipe_id = (
            st.selectbox(
                "Recipe",
                options=list(recipe_opts.keys()),
                format_func=lambda i: recipe_opts[i],
            ) if recipe_opts else None
        )

        trig = st.selectbox("Trigger", ["manual", "interval"])
        minutes = st.number_input("Interval minutes", min_value=1, value=60) if trig == "interval" else None

        ok = st.form_submit_button("Create Workflow")

    if ok:
        clean = " ".join((name or "").split())
        errors = []
        if not clean:
            errors.append("Please provide a workflow name.")
        elif clean.lower() in existing_names:
            errors.append(f"Workflow '{clean}' already exists. Pick another name.")

        if agent_id is None:
            errors.append("Select an agent for the workflow.")
        if recipe_id is None:
            errors.append("Select a recipe for the workflow.")

        if not agent_opts:
            st.info("Add an agent on the 🤖 Agents page before creating workflows.")
        if not recipe_opts:
            st.info("Create a recipe on the 📜 Recipes page before creating workflows.")

        if errors:
            for msg in errors:
                st.error(msg)
        else:
            try:
                create_workflow(
                    db,
                    name=clean,
                    agent_id=int(agent_id),
                    recipe_id=int(recipe_id),
                    trigger_type=trig,
                    trigger_value=int(minutes) if minutes else None,
                )
                st.success("Workflow created.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Failed to create workflow: {type(e).__name__}: {e}")

    # --- Existing Workflows ---
    st.subheader("Workflows")
    if not wfs:
        st.info("No workflows yet.")
    else:
        for wf in wfs:
            status = compute_status(wf)
            color = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[status]

            with st.container(border=True):
                top = st.columns([6, 1])
                top[0].markdown(
                    f"""**{wf.name}**
Agent ID: `{wf.agent_id}` · Recipe ID: `{wf.recipe_id}`
Trigger: `{wf.trigger_type}` {wf.trigger_value or ''}"""
                )
                top[1].markdown(
                    f"<div style='text-align:right;font-size:24px'>{color}</div>",
                    unsafe_allow_html=True,
                )

                cols = st.columns([1, 1, 1, 1, 3])

                with cols[0]:
                    if st.button("Run now", key=f"run-{wf.id}"):
                        try:
                            with st.spinner("Executing workflow..."):
                                run = run_now(db, wf.id)
                            # Show returned id when available
                            rid = getattr(run, "id", None) if run else None
                            st.toast(f"Run {rid or '—'} completed.", icon="✅")
                        except Exception as e:
                            st.error(f"Run failed: {type(e).__name__}: {e}")

                with cols[1]:
                    enabled = bool(wf.enabled)
                    if st.button("Enable" if not enabled else "Disable", key=f"en-{wf.id}"):
                        update_workflow(db, wf.id, enabled=0 if enabled else 1)
                        st.rerun()

                with cols[2]:
                    with st.popover("Rename"):
                        with st.form(f"rename-{wf.id}"):
                            new = st.text_input("New name", value=wf.name)
                            save = st.form_submit_button("Save")
                        if save:
                            candidate = " ".join((new or "").split())
                            if not candidate:
                                st.error("Workflow name cannot be empty.")
                            elif candidate.lower() in existing_names and existing_names[candidate.lower()] != wf.id:
                                st.error(f"Workflow '{candidate}' already exists.")
                            elif candidate == wf.name:
                                st.info("Name unchanged.")
                            else:
                                try:
                                    update_workflow(db, wf.id, name=candidate)
                                    st.success("Workflow renamed.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Rename failed: {type(e).__name__}: {e}")

                with cols[3]:
                    if st.button("Delete", key=f"del-{wf.id}"):
                        delete_workflow(db, wf.id)
                        st.rerun()

                cols[4].write(f"Last: {wf.last_run_at or '—'} · Next: {wf.next_run_at or '—'} · Status: {status}")

# --- Import / Export ----------------------------------------------------------
st.divider()
st.subheader("Import / Export")

colE, colI = st.columns(2)

with colE:
    st.markdown("**Export a bundle**")
    inc = st.multiselect(
        "Include",
        options=["agents", "recipes", "workflows"],
        default=["agents", "recipes", "workflows"],
        help="Choose the objects to include in the zip."
    )
    if st.button("Generate export"):
        data, report = export_zip(include=inc, recipes_dir="recipes")
        st.success(f"Export ready • agents={report['counts'].get('agents',0)} "
                   f"recipes={report['counts'].get('recipes',0)} "
                   f"workflows={report['counts'].get('workflows',0)}")
        st.download_button(
            label="Download .zip",
            data=data,
            file_name=f"sma-avops-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip",
            mime="application/zip",
            key="export_zip_dl",
        )
        with st.expander("Export report"):
            st.json(report)

with colI:
    st.markdown("**Import a bundle**")
    up = st.file_uploader("Upload .zip", type=["zip"])
    merge = st.radio("Merge strategy", ["skip", "overwrite", "rename"], index=0,
                     help="For duplicates by name: skip, overwrite in place, or keep both by renaming.")
    dry = st.checkbox("Dry run (preview only)", value=True)
    if up is not None and st.button("Import bundle"):
        try:
            b = up.read()
            result = import_zip(b, recipes_dir="recipes", merge=merge, dry_run=dry)
            if dry:
                st.info("Dry run preview — no changes were written.")
            st.json(result)
            if not dry:
                st.success("Import finished. Refresh the page to see changes.")
        except Exception as e:
            st.error(f"Import failed: {type(e).__name__}: {e}")
