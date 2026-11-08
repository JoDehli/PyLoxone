# Dev container

The dev container (`.devcontainer.json`) is the supported way to develop and
debug this integration. It contains Python 3.14, the project's dependencies and
Home Assistant, which runs on port 8123 and loads the Loxone integration from
this repository.

## What happens when the container is created

- The image is `mcr.microsoft.com/devcontainers/python:3.14`. It matches
  `.python-version` and `requires-python >=3.14.2`.
- `postCreateCommand` runs `scripts/setup`, which:
  1. installs the system packages `ffmpeg`, `libturbojpeg0` and `libpcap-dev`
     with `sudo apt-get` (Home Assistant needs them for its ffmpeg and camera
     integrations). They are not a devcontainer feature, because the feature
     failed to build under Podman,
  2. installs `requirements.txt` and `requirements-dev.txt`,
  3. installs `requirements-ha-integrations.txt`, the pinned packages of the
     Home Assistant integrations that `default_config` loads,
  4. links `config/custom_components` to `custom_components/` (skipped if it
     already exists), because Home Assistant only loads custom integrations
     from there,
  5. runs `hass --script ensure_config`.
- Format on save and on paste are **off**. Formatting would rewrite lines in
  open PRs. See the TODO in `.pre-commit-config.yaml`.

## Prerequisites

You need a container engine. Docker is not required on Linux.

### Linux

- **Docker** or **Podman**. Podman works with the `devcontainer` CLI and with
  VS Code, see below.
- For Podman with rootless storage on ext4, install `fuse-overlayfs`:

  ```bash
  sudo pacman -S fuse-overlayfs        # Arch; use your distro's package manager
  mkdir -p ~/.config/containers
  cat > ~/.config/containers/storage.conf <<'EOF'
  [storage]
  driver = "overlay"

  [storage.options.overlay]
  mount_program = "/usr/bin/fuse-overlayfs"
  EOF
  podman info --format '{{.Store.GraphDriverName}}'   # should print: overlay
  ```

  Without it you get `kernel does not support overlay fs`.

- For Podman the TUN module must be available for the running kernel. If the
  build fails with `pasta failed ... /dev/net/tun: No such device`, the running
  kernel and its modules do not match. This happens after a kernel update
  without a reboot. Reboot, then check with `uname -r` and
  `sudo modprobe tun`.

### macOS and Windows (not tested by the maintainer)

- **Docker Desktop** (on Windows with the WSL 2 backend), or **Podman Desktop**.
- Docker Desktop must be running before you reopen the project in the
  container.

The steps below are written for Linux. The VS Code steps should be the same on
macOS and Windows, but that is not verified yet. One known risk on Windows: the
`config/custom_components` link is created inside the container, and Git on
Windows can check out symlinks as plain text files. The link is git-ignored, so
it is only a local artefact, but check it if Home Assistant does not find the
integration.

## Starting the container

### VS Code

1. Open the repository in VS Code.
2. `Ctrl+Shift+P` (`Cmd+Shift+P` on macOS) → **Dev Containers: Reopen in
   Container**. After changes to `.devcontainer.json` use **Rebuild Container**.
3. Wait until the post-create step has finished. Check the output in the
   "Dev Containers" channel of the Output panel.

#### Podman as the engine in VS Code

Set this in your **user** settings, not in the repository, because the path
to Podman differs between machines:

```json
"dev.containers.dockerPath": "podman"
```

If VS Code reports `Docker version 17.12.0 or later required`, it looks for a
`docker` command. Install the shim package (`podman-docker` on Arch) and
restart VS Code completely. Do not click **Install** in that dialog, it tries
to install Docker.

### Command line (devcontainer CLI)

```bash
npm install -g @devcontainers/cli
cd <repo>
devcontainer up --workspace-folder . --docker-path podman   # or: docker
devcontainer exec --workspace-folder . --docker-path podman python3 --version
```

The second command should print Python 3.14.x.

## Running and debugging Home Assistant

1. In VS Code open **Run and Debug** (`Ctrl+Shift+D`).
2. Choose **Home Assistant** and press `F5`. This is the configuration in
   `.vscode/launch.json`. It runs `python -m homeassistant --debug -c config`.
3. Open `http://localhost:8123`. The first start shows the onboarding page, where
   you create a user.
4. Add the integration in **Settings → Devices & services → Add integration →
   Loxone**.

Breakpoints in `custom_components/loxone/` are hit only if the integration is
loaded, which is what the `config/custom_components` link is for.

Expected log output: the warning `We found a custom integration loxone which
has not been tested by Home Assistant` is normal. `go2rtc` is not loaded (see
`config/configuration.yaml`), and `default_config` is replaced by the same list
of integrations without it, because `go2rtc` needs a Docker binary inside the
container.

### Discovery is off in the dev container

The discovery integrations `bluetooth`, `dhcp`, `ssdp`, `usb` and `zeroconf` are
removed from `config/configuration.yaml`. The Loxone integration does not use
them. Discovery scans the network and starts integrations whose requirements are
not installed in the container, which produced `No module named ...` errors (for
example `psnawp_api` for `playstation_network`).

If you need discovery, add the integration back to `config/configuration.yaml`
yourself. Its Python packages are not in `requirements-ha-integrations.txt`. Copy
the pins from the integration's `manifest.json` (`requirements` entry) for the
Home Assistant version in `requirements-dev.txt`, then install them in the
container. Until then, the integration logs `No module named ...`.

## Tests

From the container terminal:

```bash
pytest -q
```

## Notes on the repository state

- `config/` is git-ignored except `configuration.yaml`. Home Assistant writes
  its state (`.storage/`, logs, database) there at runtime. Do not commit those.
- Never run Home Assistant as `root` in the container. Files written as root
  end up owned by a different user on the host, and Home Assistant then cannot
  write to them as `vscode`. If that happens, remove the affected files with a
  throwaway container or from a root shell.
- A local `.venv` on the host is not needed for the container workflow.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `kernel does not support overlay fs` | Podman has no rootless overlay storage | Install `fuse-overlayfs`, see above |
| `pasta failed ... /dev/net/tun: No such device` | Running kernel and modules do not match | Reboot after kernel updates |
| `Docker version 17.12.0 or later required` | VS Code looks for `docker` | Set `dockerPath` to `podman`, install `podman-docker` |
| `No module named 'hass_frontend'` (and similar) | Post-create step did not finish | Rebuild the container, or run `bash scripts/setup` in the container terminal |
| `Permission denied` on `config/.storage/...` | Files written as root in `config/` | Remove the affected files, see above |
| `ffmpeg` / `libturbojpeg` / `libpcap` errors in the log | System packages missing | Run `sudo apt-get install -y ffmpeg libturbojpeg0 libpcap-dev` in the container terminal, or run `bash scripts/setup` again |
| `go2rtc` errors | Needs a Docker binary | Expected; `go2rtc` is excluded from `config/configuration.yaml` |
