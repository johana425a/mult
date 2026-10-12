"""
CLI Skill Commands
==================

Manage local skills and install packages from external hubs (EduHub, ClawHub, …).

Hub references use ``<hub>:<slug>[@version]``; the hub prefix defaults to
``eduhub`` (DeepTutor's native open skill registry). Installs run the full
import gate: hub security verdict →
safe extraction → frontmatter adaptation (``always`` stripped, flat
``bins``/``env`` folded into ``requires``) → provenance in ``.hub-lock.json``.

In a multi-user deployment this CLI operates the owner (admin) workspace, so
an installed skill lands in the admin catalog and stays invisible to other
users until a grant assigns it.
"""

from __future__ import annotations

from rich.table import Table
import typer

from .common import console


def _resolve_token(explicit: str | None, hub: str) -> str | None:
    """Publish token precedence: --token → env → ``skill login`` store."""
    import os

    from deeptutor.services.skill import credentials

    return (
        explicit
        or os.environ.get("DEEPTUTOR_HUB_TOKEN")
        or os.environ.get("EDUHUB_TOKEN")
        or credentials.get_stored_token(hub)
    )


def _summary_table(
    title: str,
    *,
    hub: str,
    slug: str,
    version: str,
    overrides: dict[str, str],
) -> Table:
    """Confirmation table for the resolved classification (publish/update)."""
    from deeptutor.services.skill.taxonomy import domain_label, track_label

    def shown(key: str, empty: str, *, as_domain: bool = False) -> str:
        vals = [v for v in overrides.get(key, "").split(",") if v]
        if not vals:
            return empty
        return ", ".join(domain_label(v) if as_domain else v for v in vals)

    table = Table(title=title, show_header=False, title_style="bold")
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("hub", hub)
    table.add_row("slug", slug)
    table.add_row("version", version or "[red]missing[/]")
    track = overrides.get("track", "")
    table.add_row("track", f"{track_label(track)} [dim]{track}[/]" if track else f"{track_label(track)} [dim]{track}[/]")
    table.add_row("language", overrides.get("language", ""))
    table.add_row("domains", shown("domains", "[dim]General[/]", as_domain=True))
    table.add_row("stages", shown("stages", "[dim]All stages[/]"))
    table.add_row("forms", shown("forms", "[dim]—[/]"))
    table.add_row("audiences", shown("audiences", "[dim]Learner[/]"))
    table.add_row("tags", shown("tags", "[dim]—[/]"))
    return table


def register(app: typer.Typer) -> None:
    @app.command("search")
    def skill_search(
        query: str = typer.Argument(..., help="Natural-language search query."),
        hub: str | None = typer.Option(
            None, "--hub", help="Hub to search (default from settings)."
        ),
        limit: int = typer.Option(10, "--limit", min=1, max=50, help="Max results."),
    ) -> None:
        """Search a skill hub."""
        from deeptutor.services.skill.hub import HubError, default_hub, get_hub_provider

        target = (hub or default_hub()).strip().lower()
        try:
            refs = get_hub_provider(target).search(query, limit=limit)
        except HubError as exc:
            console.print(f"[bold red]Search failed:[/] {exc}")
            raise typer.Exit(code=1)
        if not refs:
            console.print("[dim]No skills matched.[/]")
            return
        table = Table(title=f"{target}: {query}")
        table.add_column("Ref", style="bold", overflow="fold")
        table.add_column("Publisher")
        table.add_column("Version")
        table.add_column("Summary")
        for ref in refs:
            install_ref = (
                f"{ref.hub}:{ref.owner_handle}/{ref.slug}"
                if ref.owner_handle
                else f"{ref.hub}:{ref.slug}"
            )
            table.add_row(
                install_ref,
                ref.owner_handle or "-",
                ref.version or "-",
                ref.summary[:100] or ref.display_name,
            )
        console.print(table)
        install_refs = [
            f"{ref.hub}:{ref.owner_handle}/{ref.slug}"
            if ref.owner_handle
            else f"{ref.hub}:{ref.slug}"
            for ref in refs
        ]
        console.print("[dim]Install with:[/] " + ", ".join(install_refs))

    @app.command("install")
    def skill_install(
        ref: str = typer.Argument(
            ...,
            help="Skill ref: <hub>:[<owner>/]<slug>[@version].",
        ),
        name: str | None = typer.Option(
            None, "--name", help="Install under a different local skill name."
        ),
        force: bool = typer.Option(
            False, "--force", help="Overwrite an existing skill with the same name."
        ),
        allow_unverified: bool = typer.Option(
            False,
            "--allow-unverified",
            help="Install even when the hub flags the package as suspicious.",
        ),
    ) -> None:
        """Install a skill from a hub into the local skill library."""
        from deeptutor.services.skill.hub import HubError, install_from_hub
        from deeptutor.services.skill.service import (
            InvalidSkillNameError,
            SkillExistsError,
            SkillImportError,
            get_skill_service,
        )

        service = get_skill_service()
        try:
            outcome = install_from_hub(
                ref,
                service=service,
                rename_to=name,
                force=force,
                allow_unverified=allow_unverified,
            )
        except SkillExistsError as exc:
            console.print(
                f"[bold red]Skill `{exc}` already exists.[/] Re-run with --force to replace it."
            )
            raise typer.Exit(code=1)
        except (HubError, SkillImportError, InvalidSkillNameError) as exc:
            console.print(f"[bold red]Install failed:[/] {exc}")
            raise typer.Exit(code=1)

        info = outcome.result.info
        verdict = outcome.verdict
        verdict_style = {"ok": "green", "suspicious": "red"}.get(verdict.status, "yellow")
        console.print(
            f"[bold green]Installed[/] [bold]{info.name}[/]"
            + (f" [dim]({outcome.ref.hub}@{outcome.ref.version})[/]" if outcome.ref.version else "")
        )
        console.print(
            f"  verdict: [{verdict_style}]{verdict.status}[/]"
            + (f" [dim]{verdict.detail}[/]" if verdict.detail else "")
        )
        if verdict.status != "ok":
            console.print(
                f"  [yellow]Review before use:[/] [dim]{service.root / info.name / 'SKILL.md'}[/]"
            )
        for entry in service.summary_entries():
            if entry.name == info.name and not entry.available:
                console.print(f"  [yellow]unavailable until:[/] {', '.join(entry.missing)}")
        for rel, reason in outcome.result.skipped:
            console.print(f"  [dim]skipped {rel} — {reason}[/]")

    @app.command("login")
    def skill_login(
        provider: str | None = typer.Argument(
            None, help="Login provider: github | google (prompt in the terminal when omitted)."
        ),
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
        no_browser: bool = typer.Option(
            False, "--no-browser", help="Print the authorization link without opening a browser."
        ),
    ) -> None:
        """Sign in to a skill hub in the browser. Save the token locally for publish and update."""
        from deeptutor.services.skill import credentials
        from deeptutor.services.skill.hub import HubError, default_hub, get_hub_provider
        from deeptutor.services.skill.taxonomy import Option

        from .skill_login import hub_origin_from_base, run_login
        from .skill_prompts import select_one

        target_hub = (hub or default_hub()).strip().lower()
        try:
            provider_obj = get_hub_provider(target_hub)
        except HubError as exc:
            console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=1)
        base_url = getattr(provider_obj, "base_url", None)
        if not base_url:
            console.print(f"[bold red]Hub `{target_hub}` does not support browser sign-in (not a clawhub hub).[/]")
            raise typer.Exit(code=1)
        origin = hub_origin_from_base(str(base_url))

        prov = (provider or "").strip().lower()
        if prov not in ("github", "google"):
            prov = select_one(
                [Option("github", "GitHub", "GitHub"), Option("google", "Google", "Google")],
                "Select a login provider",
            )

        console.print(f"[dim]Complete {prov} authorization in the browser (hub: {target_hub})…[/]")
        result = run_login(
            origin,
            prov,
            on_url=lambda u: console.print(
                f"  If the browser did not open, visit:\n  [underline]{u}[/]"
            ),
            open_browser=not no_browser,
        )
        if result.error or not result.token:
            console.print(f"[bold red]Login failed:[/] {result.error or 'No token received'}")
            raise typer.Exit(code=1)
        try:
            credentials.store_token(target_hub, result.token, login=result.login)
        except RuntimeError as exc:
            console.print(f"[bold red]Token could not be saved:[/] {exc}")
            raise typer.Exit(code=1)
        who = f" as @{result.login}" if result.login else ""
        console.print(f"[bold green]Signed in to[/] {target_hub}{who}, token saved locally.")

    @app.command("logout")
    def skill_logout(
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
    ) -> None:
        """Remove the locally saved login token for a hub."""
        from deeptutor.services.skill import credentials
        from deeptutor.services.skill.hub import default_hub

        target_hub = (hub or default_hub()).strip().lower()
        if credentials.clear_token(target_hub):
            console.print(f"[green]Signed out of[/] {target_hub}.")
        else:
            console.print(f"[dim]{target_hub} has no saved token.[/]")

    @app.command("publish")
    def skill_publish(
        directory: str = typer.Argument(..., help="Skill directory containing SKILL.md."),
        version: str | None = typer.Option(
            None, "--version", help="semver to publish; overrides SKILL.md `version:`."
        ),
        slug: str | None = typer.Option(
            None, "--slug", help="Override slug (default: SKILL.md slug/name)."
        ),
        track: str | None = typer.Option(
            None, "--track", help="Track (skips the track prompt when set)."
        ),
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
        token: str | None = typer.Option(
            None, "--token", help="Publish token; else env / `deeptutor skills login`."
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Non-interactive: take classification from SKILL.md/flags as-is (CI).",
        ),
    ) -> None:
        """Publish a skill: interactively tag it (track + facets), then upload.

        Pre-flights the package format, walks the required track (one-of) and
        optional facets — pre-filled from SKILL.md frontmatter — shows a summary
        for confirmation, then publishes. ``--yes`` skips the prompts for CI.
        """
        import sys

        from deeptutor.services.skill.hub import (
            HubError,
            default_hub,
            preflight_skill_dir,
            publish_to_hub,
            read_skill_metadata,
            resolve_publish_identity,
        )
        from deeptutor.services.skill.service import SkillImportError

        from .skill_prompts import collect_classification

        target_hub = (hub or default_hub()).strip().lower()

        # ── step 3: local format pre-flight ────────────────────────────────
        pre = preflight_skill_dir(directory)
        for warning in pre.warnings:
            console.print(f"[yellow]⚠[/] {warning}")
        if not pre.ok:
            console.print("[bold red]Format preflight failed. Fix the following:[/]")
            for err in pre.errors:
                console.print(f"  [red]✗[/] {err}")
            console.print("  [dim]Format specification: https://eduhub.deeptutor.info/skill-format.md[/]")
            raise typer.Exit(code=1)
        console.print(
            f"[green]✓[/] Format preflight passed "
            f"[dim]({pre.file_count} files, {pre.total_bytes // 1024} KB)[/]"
        )

        fm = read_skill_metadata(directory)
        interactive = (not yes) and sys.stdin.isatty()
        overrides: dict[str, str] = {}
        eff_version = (version or str(fm.get("version") or "")).strip()

        if interactive:
            # step 4: required track + optional facets, pre-filled from frontmatter
            overrides = collect_classification({**fm, "track": track or fm.get("track")})
            if not eff_version:
                eff_version = typer.prompt("\nVersion (semver)", default="1.0.0").strip()
            # step 5: confirmation summary
            preview_slug, _ = resolve_publish_identity(directory, slug=slug, version=eff_version)
            console.print(
                _summary_table(
                    "Review publication details",
                    hub=target_hub,
                    slug=preview_slug,
                    version=eff_version,
                    overrides=overrides,
                )
            )
            if not typer.confirm("Submit this publication?", default=True):
                console.print("[dim]Cancelled.[/]")
                raise typer.Exit(code=0)
        else:
            # Non-interactive (CI): track must come from --track or frontmatter.
            eff_track = track or str(fm.get("track") or "")
            if not eff_track:
                console.print(
                    "[bold red]Missing track.[/] Add --track, set track: in SKILL.md, "
                    "or omit --yes to choose labels interactively."
                )
                raise typer.Exit(code=1)

        tok = _resolve_token(token, target_hub)
        if not tok:
            console.print(
                "[bold red]Not signed in.[/] Run [bold]deeptutor skills login[/] to complete browser authorization, "
                "or supply a token through --token / $DEEPTUTOR_HUB_TOKEN."
            )
            raise typer.Exit(code=1)

        try:
            outcome = publish_to_hub(
                directory,
                token=tok,
                version=eff_version or None,
                slug=slug,
                track=track,
                hub=target_hub,
                overrides=overrides or None,
            )
        except (HubError, SkillImportError) as exc:
            console.print(f"[bold red]Publish failed:[/] {exc}")
            raise typer.Exit(code=1)

        console.print(
            f"[bold green]Published[/] [bold]{outcome.slug}@{outcome.version}[/] → {outcome.hub}"
        )
        console.print(
            f"  [dim]install with:[/] deeptutor skill install {outcome.hub}:{outcome.slug}"
        )

    @app.command("update")
    def skill_update(
        directory: str | None = typer.Argument(
            None, help="Skill directory for an upgrade; not needed for rollback."
        ),
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
        token: str | None = typer.Option(
            None, "--token", help="Publish token; else env / `deeptutor skills login`."
        ),
    ) -> None:
        """Manage published skills: list your skills, select one, then roll back or publish a new version.

        Upgrades reuse the current track and labels by default; rollback
        moves the latest pointer to an earlier published version without creating a version.
        """
        import sys

        from deeptutor.services.skill.hub import (
            HubError,
            default_hub,
            get_hub_provider,
            preflight_skill_dir,
            publish_to_hub,
        )
        from deeptutor.services.skill.service import SkillImportError
        from deeptutor.services.skill.taxonomy import Option

        from .skill_prompts import collect_classification, select_one

        target_hub = (hub or default_hub()).strip().lower()
        if not sys.stdin.isatty():
            console.print("[bold red]update is an interactive command. Run it in a terminal.[/]")
            raise typer.Exit(code=1)

        tok = _resolve_token(token, target_hub)
        if not tok:
            console.print(
                "[bold red]Not signed in.[/] Run [bold]deeptutor skills login[/] to complete browser authorization, "
                "or supply the token through --token."
            )
            raise typer.Exit(code=1)

        provider = get_hub_provider(target_hub)
        lister = getattr(provider, "list_my_skills", None)
        if not callable(lister):
            console.print(f"[bold red]Hub `{target_hub}` cannot list published skills.[/]")
            raise typer.Exit(code=1)
        try:
            mine = [s for s in lister(tok) if s.get("slug")]
        except HubError as exc:
            console.print(f"[bold red]Could not fetch:[/] {exc}")
            raise typer.Exit(code=1)
        if not mine:
            console.print(f"[dim]You have not published any skills to {target_hub}.[/]")
            raise typer.Exit(code=0)

        # ── step 3: pick a skill, then pick the action ────────────────────
        skill_opts = [
            Option(
                str(s["slug"]),
                f"{s.get('displayName') or s['slug']}  v{s.get('version') or '-'}",
                str(s["slug"]),
            )
            for s in mine
        ]
        chosen_slug = select_one(skill_opts, "Select a skill to update")
        chosen = next(s for s in mine if s.get("slug") == chosen_slug)
        versions = [str(v) for v in (chosen.get("versions") or [])]
        current = str(chosen.get("version") or "")

        action = select_one(
            [
                Option("rollback", "Roll back", "Roll back"),
                Option("upgrade", "Publish a new version", "Publish a new version"),
            ],
            f"What would you like to do with {chosen_slug}?",
        )

        # ── rollback: move latest to an older version ─────────────────────
        if action == "rollback":
            if len([v for v in versions if v != current]) == 0:
                console.print(f"[dim]{chosen_slug} has only one version ({current}); rollback is unavailable.[/]")
                raise typer.Exit(code=0)
            version_opts = [Option(v, "" if v == current else "", v) for v in versions]
            target_version = select_one(version_opts, "Which version should latest point to?")
            if target_version == current:
                console.print("[dim]This is already latest; no rollback is needed.[/]")
                raise typer.Exit(code=0)
            if not typer.confirm(
                f"Roll {chosen_slug} latest back from {current or '-'} to {target_version}?",
                default=True,
            ):
                console.print("[dim]Cancelled.[/]")
                raise typer.Exit(code=0)
            tag_setter = getattr(provider, "set_dist_tag", None)
            if not callable(tag_setter):
                console.print(f"[bold red]Hub `{target_hub}` does not support rolling back latest.[/]")
                raise typer.Exit(code=1)
            try:
                tag_setter(chosen_slug, version=target_version, token=tok)
            except HubError as exc:
                console.print(f"[bold red]Rollback failed:[/] {exc}")
                raise typer.Exit(code=1)
            console.print(
                f"[bold green]Rolled back[/] {chosen_slug} latest → [bold]{target_version}[/]"
            )
            return

        # ── upgrade: publish a new version (tags default to current) ──────
        if not directory:
            directory = typer.prompt("Path to the new skill directory").strip()
        pre = preflight_skill_dir(directory)
        for warning in pre.warnings:
            console.print(f"[yellow]⚠[/] {warning}")
        if not pre.ok:
            console.print("[bold red]Format preflight failed. Fix the following:[/]")
            for err in pre.errors:
                console.print(f"  [red]✗[/] {err}")
            raise typer.Exit(code=1)
        console.print(
            f"[green]✓[/] Format preflight passed "
            f"[dim]({pre.file_count} files, {pre.total_bytes // 1024} KB)[/]"
        )

        overrides = collect_classification(chosen)
        new_version = typer.prompt(
            f"\nNew version (semver, current latest = {current or '-'})"
        ).strip()

        console.print(
            _summary_table(
                "Review upgrade details",
                hub=target_hub,
                slug=chosen_slug,
                version=new_version,
                overrides=overrides,
            )
        )
        if not typer.confirm("Publish this new version?", default=True):
            console.print("[dim]Cancelled.[/]")
            raise typer.Exit(code=0)

        try:
            outcome = publish_to_hub(
                directory,
                token=tok,
                version=new_version or None,
                slug=chosen_slug,
                hub=target_hub,
                overrides=overrides,
            )
        except (HubError, SkillImportError) as exc:
            console.print(f"[bold red]Update failed:[/] {exc}")
            raise typer.Exit(code=1)
        console.print(
            f"[bold green]Updated[/] [bold]{outcome.slug}@{outcome.version}[/] → {outcome.hub}"
        )

    @app.command("list")
    def skill_list() -> None:
        """List local skills, including hub provenance."""
        from deeptutor.services.skill.service import get_skill_service

        service = get_skill_service()
        table = Table(title="Skills")
        table.add_column("Name", style="bold")
        table.add_column("Source")
        table.add_column("Origin")
        table.add_column("Description")
        for info in service.list_skills():
            origin = service.hub_origin(info.name)
            origin_label = "-"
            if origin:
                version = str(origin.get("version") or "").strip()
                origin_label = str(origin.get("hub") or "hub") + (f"@{version}" if version else "")
            table.add_row(info.name, info.source, origin_label, info.description[:80])
        console.print(table)

    @app.command("remove")
    def skill_remove(
        name: str = typer.Argument(..., help="Skill name to remove."),
    ) -> None:
        """Remove a user-layer skill (builtin skills are read-only)."""
        from deeptutor.services.skill.service import (
            InvalidSkillNameError,
            SkillNotFoundError,
            SkillReadOnlyError,
            get_skill_service,
        )

        try:
            get_skill_service().delete(name)
        except (SkillNotFoundError, InvalidSkillNameError):
            console.print(f"[bold red]Skill not found:[/] {name}")
            raise typer.Exit(code=1)
        except SkillReadOnlyError as exc:
            console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=1)
        console.print(f"[green]Removed[/] {name}")
