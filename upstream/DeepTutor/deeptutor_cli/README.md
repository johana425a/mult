# DeepSteam CLI

The upstream Python command name is retained for package and API compatibility. The desktop product is DeepSteam.

## Install

```text
pip install -e .
```

Use the Python version and dependency groups declared in `pyproject.toml`. Runtime settings are stored under the application's data directory; project-root environment files are not the normal settings source.

## Chat and capabilities

```text
deeptutor chat
deeptutor run chat "Explain the Fourier transform"
deeptutor run deep_solve "Solve x^2=4"
deeptutor run visualize "Animate a sine wave"
deeptutor run deep_research "Compare two retrieval approaches"
```

The interactive chat supports retry and regeneration. Capability selection uses the shared durable turn service, tool registry and selected model connection. Tool toggles do not bypass context or capability requirements.

## Knowledge and records

```text
deeptutor kb list
deeptutor kb create example --doc textbook.pdf
deeptutor memory show
deeptutor partner list
```

Workspace document reading is available independently of semantic retrieval. A knowledge-base index may require an embedding provider; selecting a workspace folder does not require one for direct document reading.

## Skills

Use `deeptutor skills --help` for local skill management and hub publication. Browser login saves the hub token in the user's own local profile. Publication validates the skill format, version, track and labels before submission. Update can publish a new version or roll the `latest` pointer back to an existing version.

Do not commit runtime profiles, tokens, settings, uploaded documents or learning records. The public repository contains source and license notices, with English defaults and no user-specific installation paths.

## Services

`deeptutor serve` starts the API service; `deeptutor start` manages the backend and frontend together. Desktop startup manages its own internal services. Users do not need to copy an address from someone else's computer.

## Development

Install the development dependency group for tests and linting. Run tests against isolated data and simulated providers when verifying configuration, recovery and deletion. Live provider calls need explicit authorization and valid user-owned credentials.
