# The `dhis2` connection

One `dhis2` connection is one DHIS2 instance and the credential to talk to it. Every block in
this pack takes a `connection` field naming one by its `code`, and builds its client from that
row: the URL, the credential, the TLS setting and the timeout all come from the connection,
never from a step.

## Settings

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `base_url` | `string` | yes |  | The instance root every request path is resolved against, version pin included. |
| `api_token` | `string (password) or null` |  | `null` | A personal access token, sent as `Authorization: ApiToken`. |
| `basic_username` | `string or null` |  | `null` | The user half of HTTP basic authentication. |
| `basic_password` | `string (password) or null` |  | `null` | The secret half of HTTP basic authentication. |
| `verify_tls` | `boolean` |  | `true` | Whether certificates are verified; turning this off is a per-connection decision. |
| `timeout` | `string (humane-duration)` |  | `"30s"` | The timeout applied to every request through this connection. |

`api_token` and `basic_password` are the secret fields: they are encrypted at rest with the
instance key and redacted in every read, so `dg connection show` and the API answer with the
field present and its value withheld.

`timeout` is a duration, written the way a document writes one -- `30s`, `2m` -- and it must be
greater than zero.

## One credential, not two

A connection carries a personal access token or a basic username and password, and the model
refuses anything else:

- both an `api_token` and a `basic_username` is refused,
- neither is refused,
- a `basic_username` without a `basic_password` is refused.

A refusal happens when the connection is created or updated, not when a step first runs.

## `base_url` names the host that answers

Name the host the instance actually answers on, with the version pin if it has one. A redirect
to another origin arrives without the credential, because the client drops the `Authorization`
header when the origin changes. `https://play.dhis2.org/demo` is an alias that redirects across
hosts for exactly this reason: resolve it once and name the versioned host it resolves to.

```bash
curl -sSI https://play.dhis2.org/demo
```

## Creating one

```bash
dg connection create dhis2 play \
  --name "DHIS2 play demo" \
  --set base_url=https://play.im.dhis2.org/stable-2-43-1 \
  --set basic_username=admin \
  --set basic_password=district
```

With a personal access token instead:

```bash
dg connection create dhis2 production \
  --set base_url=https://dhis.example.org \
  --set api_token="$DHIS2_TOKEN" \
  --set timeout=1m
```

`dg connection create` talks to the server and needs a token. `dg connection ensure` is the
process-side twin that writes the row itself, for a bootstrap container that has none; it is
declarative, so a field left out is cleared rather than kept.

A step then names the connection by its code:

```yaml
steps:
  export:
    block: dhis2.data_value_set_export
    config:
      connection: play
      data_set: BfMAe6Itzgt
      period: 2026Q1
      org_unit: ImspTQPwCqd
```

## Checking one

```bash
dg connection check play
```

The check builds the client from the stored config and opens it, which reads
`/api/system/info` with the credential attached. So a healthy verdict means the URL resolves,
the TLS setting works, the credential is accepted, and the version is the instance's own word
for itself rather than something inferred from an `/api/N` path.

The command writes one `connection.checked` record, carrying the `code`, whether it is
`healthy`, the `version` the instance reported, and a `detail` line naming the failure when it
is not. A check never raises: an unreachable host, a refused credential and a version the
client does not speak all come back as an unhealthy report with the reason in `detail`.

## What a block does with it

Each block call opens its own client for the length of that call, from the connection's config
as it is at that moment. There is no pooled client held between steps, so rotating a
credential takes effect on the next step rather than on the next process restart.
