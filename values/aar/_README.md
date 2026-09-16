# values/aar/ — the site's traffic policy, one file per site

`values/aar/<site_code>.yaml` holds the **whole** Application Priority traffic
policy for that site — QoS classification *and* app-aware routing, merged — and
**every site must have one**: `generate.py` aborts with a named error if the
file is missing, rather than silently producing a site with no traffic policy.

The file name must match the `site_code` of `values/<site>.yaml`, lowercased —
`values/bxt.yaml` pairs with `values/aar/bxt.yaml`.

> The directory name is now a misnomer (it holds more than app-aware routing).
> Renaming it touches `generate.py`, `CLAUDE.md` and `README.md`; left as a
> deliberate follow-up.

## Why ONE policy and not two

UX1 ran two independent policies over the same traffic: a data policy
(`BXS-BXT_QOSClass_V5` / `LO_QOSClass_V3`, direction `all`) doing DSCP marking,
forwarding-class assignment and local-TLOC pinning, and `LO_AAR`
(direction `service`) doing SLA-based path selection.

Splitting them the same way in UX2 was rejected on a live apply, 2026-09-04:

```
PPARC0008  Multiple traffic policies cannot be added for same vpn and same
           direction:{ 10,all } for traffic policy QOSCLASS-BXT and AAR-BXT
```

vManage allows several traffic policies in one profile, but not two that overlap
on (VPN, direction) — and `all` subsumes `service`. So the two are merged into
one parcel, `TRAFFIC-<SITE>`, direction `all`.

Because the merged parcel carries `preferred_colors`, which is per-site, the
whole policy is per-site. That is why this directory exists.

## How the merge reproduces UX1

In UX1 a packet takes the first match in *each* policy and receives both sets of
actions. Here only one sequence matches, so **each sequence carries the union of
the actions both UX1 policies would have applied**. The module allows it:
`sla_class` and `dscp` / `forwarding_class` / `local_tloc` coexist in one
`actions` block.

Sequence order follows the UX1 data policy (DSCP, then applications, then
prefix/port, then catch-all). Both UX1 policies order DSCP first, so this order
is faithful in both dimensions. The sequences just before the catch-all are the
matches only `LO_AAR` carried; they get the forwarding class the UX1 default
would have given them (`LO_BESTEFFORT`) plus their SLA.

### Known residual divergence

Two independent first-match policies cannot be reproduced exactly by one without
partitioning the product of both. One case is lost: **DSCP 32**. `LO_AAR` gives
it `LO_SLA_VIDEO`, but no data-policy sequence matches 32, so its sequence sits
near the end — a DSCP-32 packet that already matches an earlier prefix/port
sequence (Commvault, Backup, TUBE, SCAVENGER) keeps the data-policy treatment
but loses `LO_SLA_VIDEO`. Moving it up would instead cost those sequences their
`local_tloc`. Narrow traffic either way; documented rather than hidden.

### Inherited contradiction

`COMMVAULT_SIN_TO_SERVERS` pins traffic to `local_tloc` custom2/custom1 while
its `sla_class` asks for the site's `preferred_colors` (private on BXT/BEL).
Both were genuinely set in UX1 on the same traffic. Kept as-is because a strict
reproduction was requested — but it is worth arbitrating one day.

## Why the AAR is per-site and the rest of the policy is not

Everything else in the Application Priority profile is shared:

| Part | Lives in | Scope |
|---|---|---|
| `QOSCLASS-<SITE>` (QoS classification) | `templates/_shared/application-priority-common.yaml` | fabric-wide |
| `QOS-<SITE>` (scheduler) | `templates/{dc,branch}/application-priority.yaml` | per variant |
| `AAR-<SITE>` (app-aware routing) | **here**, `values/aar/<site>.yaml` | **per site** |

The AAR is the one part whose values are genuinely site-specific:
`preferred_colors` may only name colors the site's own transports actually
carry, and the lab sites already differ —

| Site | Colors present | AAR preferred_colors |
|---|---|---|
| BXT (`branch-a-routed`) | custom1, custom2, private1, private2 | private1, private2 |
| BEL (`dc`) | custom1, custom2, private1 | private1 |
| CML (`branch-b-routed`) | custom1, custom2 | custom1, custom2 |

Naming a color the site does not have is NOT fatal, and `strict` does not make
it fatal either — see "What preferred_colors actually does" below.  The reason
to keep the list truthful is legibility and drift detection, not breakage.

## What preferred_colors actually does

Order of operations for one AAR sequence, per Cisco's app-route semantics
(TODO confirm on the fabric at the first apply):

1. Take every data-plane tunnel available for the traffic.
2. Keep those that MEET the SLA class (loss / latency / jitter thresholds).
3. Among the survivors of step 2, prefer the ones whose color is listed in
   `preferred_colors`.
4. If NO surviving tunnel carries a preferred color, use any surviving tunnel
   anyway — the preference is a hint, not a filter.
5. If step 2 left NOTHING (no tunnel meets the SLA at all):
   - default: traffic still flows, on the best available path;
   - with `strict: true`: traffic is DROPPED.

Two consequences worth being explicit about:

- **A color that does not exist on the site is a no-op.**  Step 3 matches
  nothing, step 4 takes over, and the result is identical to writing no
  `preferred_colors` at all.  Nothing breaks.
- **`strict` is about step 5, not about step 3.**  It reacts to "no tunnel
  meets the SLA", which is a completely separate condition from "no tunnel
  carries the preferred color".  Setting `strict` on a sequence whose
  preferred colors are absent does NOT drop the traffic.

### `fallback_to_best_path` and `counter_name`

Two more knobs sit next to `preferred_colors`, both carried over verbatim from
UX1's `LO_AAR` (added 2026-09-04 after comparing sequence by sequence against
`DATA/policies.json` — they had been missed in the first migration pass):

- `sla_class.fallback_to_best_path: true` — acts on **step 5**: when no tunnel
  meets the SLA, take the best available path rather than leaving the default
  behaviour decide.  It is the opposite of `strict`.  UX1 sets it on sequences
  61, 71 and 81, i.e. our sequences 4, 5 and 6 (Commvault both directions and
  Backup).  The first three sequences deliberately do NOT have it, matching UX1.
- `counter_name: "LO_COMMVAULT_Count"` — a named traffic counter, on sequences
  4 and 5 only.  It is NOT a parcel, just an attribute inside the traffic
  policy, so it takes no `-<SITE>` suffix; each device keeps its own counter
  under that same name.


So why keep the lists truthful per site?  Because they are documentation that
the device cannot contradict: an AAR listing `private1` on an internet-only
site tells the next reader that MPLS exists there, and a stale or mistyped
color is indistinguishable from a deliberate one.  A no-op today is a wrong
answer during the next incident.

## How it is processed

`generate.py` renders this file through exactly the same pipeline as
`templates/`: `__SITE__` is replaced with the site code, and any scalar written
`__GLOBAL:<dotted.key>__` is resolved from `globals.yaml`.  Output lands in
`sites/<site>/data/aar.yaml` and the NaC module merges it onto the
`APP-PRIORITY-<SITE>` profile declared in the shared template (lists of dicts
merge by `name`, so `traffic_policies` ends up holding both AAR and QOSCLASS).

Write `__SITE__` rather than the literal site code even though the file is
already site-specific: copying a file to onboard a new site is then safe, where
a forgotten literal `AAR-BXT` in `values/aar/new.yaml` would collide with BXT's
parcel (PPARC0012, parcel names are unique tenant-wide).

## Adding a site

1. Copy the closest existing file — same variant if possible.
2. Set `preferred_colors` on each sequence to colors that site really has
   (check `vpn0_*_color` / `tloc_ext_tunnel_color` in `values/<site>.yaml`).
3. Run `python3 generate.py --site <site>` and check the placeholder report.

Object names referenced here (`LO_SLA_*-__SITE__`, `LO_Teams_Video-__SITE__`,
`LO_COMMVAULT_*-__SITE__`, `LO_BACKUP_SERVERS-__SITE__`) are declared in
`templates/_shared/policy-objects-common.yaml`.  A reference that does not
resolve there is caught by `validate_model.py`, not by terraform.
