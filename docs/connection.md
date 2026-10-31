# The `dhis2` connection

One `dhis2` connection is one DHIS2 instance and the credential to talk to it. Every block in
this pack takes a `connection` field naming one by its `code`, and builds its client from that
row: the URL, the credential, the TLS setting and the timeout all come from the connection,
never from a step.

## Settings

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `base_url` | `string` | yes |  | The instance root every request path is resolved against, version pin included. |
| `api_token` | `string (password) or null` |  | `null` | A personal access token, sent as `Authorization: ApiToken`: visible ASCII with no whitespace. |
| `basic_username` | `string or null` |  | `null` | The user half of HTTP basic authentication. |
| `basic_password` | `string (password) or null` |  | `null` | The secret half of HTTP basic authentication. |
| `verify_tls` | `boolean` |  | `true` | Whether certificates are verified; turning this off is a per-connection decision. |
| `follow_redirects_with_auth` | `boolean` |  | `false` | Whether the URL `base_url` redirects to is used whatever its host or scheme, credential and all. |
| `timeout` | `string (humane-duration)` |  | `"30s"` | The timeout applied to every request through this connection. |

`api_token` and `basic_password` are the secret fields: they are encrypted at rest with the
instance key and redacted in every read, so `dg connection show` and the API answer with the
field present and its value withheld.

`timeout` is a duration, written the way a document writes one -- `30s`, `2m` -- and it must be
greater than zero.

## One credential, not two

A connection carries a personal access token or a basic username and password, and the model
refuses anything else:

- an `api_token` beside a `basic_username` or a `basic_password` is refused,
- neither is refused,
- a `basic_username` without a `basic_password` is refused.

An `api_token` holding anything but visible ASCII, such as the trailing newline a pasted or
file-read token brings with it, is refused too, because it cannot be sent as a header value. The
refusal does not repeat the value. A basic password is base64-encoded on the way to the header and
takes any text.

A refusal happens when the connection is created or updated, not when a step first runs. A row
stored before a rule existed fails when it is next read: its check is unhealthy and its steps fail.

## A `base_url` that redirects

A client follows `base_url`'s redirects once, without the credential, and talks to where they
land when all of these hold:

- the target keeps the scheme,
- the target's host is `base_url`'s host, a subdomain of it, or under `dhis2.org` beside it,
- the target answers an anonymous `/api/system/info` like DHIS2: JSON with a `version` or
  `contextPath`, or DHIS2's own error envelope.

Any other target never receives the credential: an open redirect or a sign-in page does not, and
neither does a host that only shares its last labels with `base_url`. `dhis2.health.co.uk` and
`attacker.co.uk` end alike and have different registrants, and so do two names under a shared
platform domain such as `azurewebsites.net` or `github.io`. The connection stays on `base_url`, or
its check and steps fail with `dhis2.connection.redirect_refused`, naming the target.

Two sibling hosts under one domain of your own are not told apart from those, so
`dhis2.example.org` redirecting to `hmis.example.org` is not followed either. Set `base_url` to the
target.

The answer to `/api/system/info` is something any host can send, so that test tells DHIS2 from a
sign-in page and says nothing about who holds the target. The rule on the host is what keeps the
credential in place.

`https://play.dhis2.org/2.43` and `https://play.dhis2.org/2.42` are aliases for the newest play
demo of each major, and resolve this way: a connection naming one follows the demo as it moves.
`http://play.dhis2.org/2.43` lands on `https://`, a change of scheme that is never followed on its
own. `follow_redirects_with_auth: true` follows any redirect, to any host or scheme, and sends the
credential there; set it only on a `base_url` whose redirect you trust.

## Creating one

```bash
dg connection create dhis2 play \
  --name "DHIS2 play demo" \
  --set base_url=https://play.dhis2.org/2.43 \
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
A check may also answer neither way: `healthy` is `null` when a kind cannot decide, which
this kind never does, since an instance either answers `/api/system/info` or it does not.

## What a block does with it

Each block call opens its own client for the length of that call, from the connection's config
as it is at that moment. There is no pooled client held between steps, so rotating a
credential takes effect on the next step rather than on the next process restart.
