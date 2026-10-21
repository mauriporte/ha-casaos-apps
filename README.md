# CasaOS / ZimaOS apps for Home Assistant

See and edit your CasaOS / ZimaOS apps from a Home Assistant dashboard. A **⋯** on each app tile opens a popup
like ZimaOS's own *Edit app* window: a **Form** tab (title, web address, image and tag, restart policy, network,
ports, folders, variables, and under *Advanced* devices, CPU, memory, privileged mode, capabilities and command) and a
**YAML** tab with the compose file itself. Both are editable and stay in step when you switch tabs. **Save** checks the
change with CasaOS first and then applies it, which recreates the app's containers, exactly like pressing Save in
CasaOS / ZimaOS.

Containers that CasaOS doesn't manage (made with `docker run`) open read-only, with their settings read through
Home Assistant's **Portainer** integration, when it's set up for that server.

The popup follows your Home Assistant theme, and has *copy YAML*, *fullscreen* and *open in CasaOS / ZimaOS*
buttons. On a computer the ⋯ appears when you hover a tile; on touch screens it's always shown.

## Install

1. Copy `custom_components/casaos_apps` into your Home Assistant `config/custom_components/` (or add this repository
   to HACS as a custom integration) and restart Home Assistant.
2. **Settings → Devices & services → Add integration → CasaOS / ZimaOS apps**, once per server: a name (used in
   dashboards, e.g. `NAS`), its IP address, and the same username and password as its web interface.
3. **Settings → Dashboards → ⋮ → Resources → Add resource**: `/casaos_apps/casaos-app-menu.js`, type *JavaScript module*.

## Use it on a tile

The menu is a [picture-elements](https://www.home-assistant.io/dashboards/picture-elements/) element, so it sits on top
of any app button made with that card:

```yaml
type: picture-elements
image: …
elements:
  - type: image
    entity: switch.jellyfin_container
    # …
  - type: custom:casaos-app-menu
    server: NAS          # the integration entry's name (or its IP)
    container: jellyfin  # the container's name, or the CasaOS app id
    style: {top: 10%, left: 88%}
```

## Security

Only Home Assistant **admin** users can open or save the popup, because compose files hold secrets and saving one
recreates containers. The login is stored in the integration's config entry, like any other integration's. Variables
whose names look like secrets (`PASSWORD`, `TOKEN`, `KEY`, …) are masked in the form until you click into them.

## How it works

The integration uses the CasaOS app management API that the CasaOS / ZimaOS web interface itself uses
(`/v2/app_management/compose`), and offers four admin-only WebSocket commands to the frontend:
`casaos_apps/servers`, `casaos_apps/app` (an app's compose file, by container name), `casaos_apps/convert`
(Form ↔ YAML) and `casaos_apps/save` (validate, then apply).

Note for ZimaOS: when it installs or updates an app it always downloads the image first, even with
`pull_policy: never`, so an app whose image was built locally on the server can't be (re)installed until that image is
published to a registry.

Tests: `python -m pytest tests`

## License

MIT
