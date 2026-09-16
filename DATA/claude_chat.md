# Point de reprise — Session Claude Code
# Projet : nac4 — Cisco SD-WAN NaC (netascode/nac-sdwan v1.4.0)
# Date dernière session : 2026-09-01

---

## Contexte rapide du repo

- Repo `nac4` : NaC SD-WAN basé sur le module Terraform `netascode/nac-sdwan/sdwan` v1.4.0
- Paradigme UX2 exclusivement (config groups + parcels, pas de feature templates UX1)
- `generate.py` lit `templates/` + `values/*.yaml` + `globals.yaml` et génère les roots Terraform dans `sites/`
- Un tfstate par site : `sites/bxt/`, `sites/cml/`, `sites/bel/`
- Sites réels : **BEL** (DC hub, site_id 1100, jamais appliqué), **BXT** (branch lab, site_id 110, live), **CML** (branch, site_id 3, non encore déployé)

---

## Ce qui a été fait en session 2026-09-01 (claude-upd_010926.log)

Implémentation de l'Application Priority Profile (QoS + AAR) en UX2 :

| Fichier | Action | Contenu |
|---|---|---|
| `globals.yaml` | MOD | Ajout sections `commvault.*` + `backup.*` (placeholders CIDRs) + `dhcp.dns_servers` |
| `templates/branch/policy-objects.yaml` | MOD | forwarding_classes (7 classes LO_VOICE…LO_BESTEFFORT), sla_classes (4), application_lists (LO_Teams_Video), ipv4_data_prefix_lists (Commvault/Backup via `__GLOBAL:`) |
| `templates/branch/application-priority.yaml` | ADD | APP-PRIORITY-__SITE__ : QOS-__SITE__ (LO_QOSMAP_V2, 7 schedulers) + AAR-__SITE__ (6 séquences LO_AAR) |
| `templates/dc/policy-objects.yaml` | ADD | PO-BEL : forwarding_classes LO_QOSMAP V1 (8 classes), SLA classes, app lists, data prefix lists |
| `templates/dc/application-priority.yaml` | ADD | APP-PRIORITY-BEL : QOS-BEL (LO_QOSMAP V1, 8 schedulers) + AAR-BEL (6 séquences) |
| `templates/dc/config-group.yaml` | MOD | Ajout `policy_object_profile: "PO-BEL"` |
| `templates/_shared/policy.yaml` | MOD | Ajout `application_priority: "APP-PRIORITY-__SITE__"` dans PG-__SITE__ |
| `variants.yaml` | MOD | Ajout application-priority.yaml + policy-objects.yaml au variant dc ; application-priority.yaml aux variants branch |
| `known_object_names.yaml` | MOD | 22 nouveaux noms : forwarding classes, SLA classes, data prefix lists, séquences AAR |

### TODO avant terraform plan (toujours ouvert)

Compléter dans `globals.yaml` (les 3 placeholders de cette session) :
```yaml
commvault:
  sin_server_prefixes:   # renseigner CIDRs réels
  server_prefixes:       # renseigner CIDRs réels
backup:
  server_prefixes:       # renseigner CIDRs réels
```
Puis relancer : `python3 generate.py`

---

## Éléments laissés hors scope — statut et raisons

### 1. OSPF_TO_OMP_DNEY_DEFAULT — différé, basse priorité
Route-policy qui bloque la redistribution de la route default OSPF vers OMP.
En UX2 : se contrôle via le parcel `transport_ospf`. Pas encore vérifié si nac-sdwan 1.4.0 expose ce knob dans `templates/branch/transport-a.yaml`. Décision : laisser de côté pour l'instant.

### 2. OMP_TO_BGP_2000_MED — différé, basse priorité
Route-map identique à `OMP_TO_BGP_1000_MED` mais MED 2000 (chemin de secours).
Non référencée par des voisins précis — il faudrait d'abord décider quel router/voisin l'utilise (par ex. router2 = backup). Décision : laisser de côté, à traiter quand le besoin de traffic engineering asymétrique se précise.

### 3. cflowd — différé explicitement
Flow telemetry vSmart-level. Reste une centralized policy classique en UX2 (pas de remplacement UX2 natif). Sera traité dans le même root `sites/fabric/` que la topology — mais dans une session ultérieure.

### 4. Control policies (centralized) — EN COURS DE CONCEPTION, voir section suivante

---

## Sujet de la prochaine session : sites/fabric/ — hub-and-spoke topology

### Décisions arrêtées dans cette session

**Architecture :**
- La centralized policy (topology hub-and-spoke) est un objet vManage unique géré par vSmart
- Elle ne peut PAS être dans les roots par site (doublon → échec ou écrasement)
- Solution : un root Terraform dédié `sites/fabric/` avec son propre tfstate
- `generate.py` génère `sites/fabric/data/` depuis `templates/fabric/` (nouveau dossier à créer)

**Il n'y a pas d'équivalent UX2 natif pour la topology policy** :
- AAR → Application Priority Profile (UX2, device-level) ✓ déjà fait
- Hub-and-spoke → reste `sdwan_centralized_policy` (vSmart-level, UX1-style) → `sites/fabric/`
- cflowd → même constat, même root → session future

**Les deux couches coexistent** : config groups UX2 (device config) + centralized policy vSmart (plan de contrôle). C'est voulu par Cisco.

**Structure cible :**
```
sites/
  bxt/          ← tfstate BXT  (config device)
  cml/          ← tfstate CML  (config device)
  bel/          ← tfstate BEL  (config device)
  fabric/       ← tfstate FABRIC  ← À CRÉER
    main.tf
    providers.tf
    data/
      centralized-policy.yaml
```

**Séquence d'apply :**
1. `sites/bel/` — DC hub devices (rarement touché)
2. `sites/fabric/` — topology activée (après que les devices existent)
3. `sites/bxt/`, `sites/cml/` — branches, ordre libre

**Policy objects dans `sites/fabric/` :**
Le module a deux tracks d'objets qui n'interagissent PAS :

| Track | YAML source | Ressource Terraform | Utilisé par |
|---|---|---|---|
| Classique (UX1) | `sdwan.policy_objects.*` | `sdwan_data_ipv4_prefix_list_policy_object` | Centralized policies (vSmart) |
| UX2 | `sdwan.feature_profiles.policy_object_profile.*` | `sdwan_policy_object_data_ipv4_prefix_list` | Application priority profiles |

`sites/fabric/` utilisera uniquement le track classique. Les data prefix lists UX2 des branches (Commvault, Backup) ne peuvent PAS être partagées depuis `sites/fabric/` — elles restent per-site, c'est correct.

**Contenu de `sites/fabric/` (première passe) :**
```yaml
sdwan:
  policy_objects:
    site_lists:
      - name: "SL-DC-HUB"
        site_ids: [1100]          # BEL
      - name: "SL-BRANCHES"
        site_ids: [110, 3]        # BXT, CML — déclaré manuellement (décision prise)
    vpn_lists:
      - name: "VL-ALL"
        vpn_ids: [10]

  centralized_policies:
    definitions:
      control_policy:
        hub_and_spoke_topology:
          - name: "HUB-AND-SPOKE"
            description: "..."
            vpn_list: "VL-ALL"
            hub_and_spoke_sites:
              - name: "PRIMARY"
                spokes:
                  - site_list: "SL-BRANCHES"
                    hubs:
                      - site_list: "SL-DC-HUB"
    feature_policies:
      - name: "LO_CENTRAL_POLICY_V5"
        description: "..."
        hub_and_spoke_topology:
          - policy_definition: "HUB-AND-SPOKE"
            site_region:
              site_lists_in: ["SL-BRANCHES"]
    activated_policy: "LO_CENTRAL_POLICY_V5"
```

### Ce qu'il faut pour démarrer l'implémentation

1. **Détails de LO_CENTRAL_POLICY_V5 depuis vManage** (l'utilisateur a confirmé y avoir accès) :
   - Noms exacts des site lists existantes
   - VPN list(s) utilisées
   - Noms des topology definitions
   - Ces infos sont nécessaires pour le `terraform import` (la policy existe déjà en vManage)

2. **`terraform import`** sera nécessaire sur le premier apply de `sites/fabric/` pour adopter la policy existante sans la recréer.

3. **`generate.py`** devra être étendu pour gérer le variant `fabric` (pas de `__SITE__`, pas de routers, pas de config group — seulement centralized_policies + policy_objects classiques).

---

## Rappels techniques importants pour la prochaine session

- `sdwan_centralized_policies.tf` : le module crée `sdwan_centralized_policy`, `sdwan_hub_and_spoke_topology_policy_definition`, `sdwan_site_list_policy_object`, `sdwan_vpn_list_policy_object`, `sdwan_activate_centralized_policy`
- Le `depends_on` du module sur `sdwan_attach_feature_device_template` est inerte en UX2 (pas de device templates) — pas un problème
- La site list `SL-BRANCHES` sera déclarée manuellement dans `templates/fabric/` (pas auto-générée depuis values/)
- DSCP toujours en décimal entier (jamais de keyword PHB)
- Ne jamais modifier `sites/*/` directement — toujours passer par `generate.py`
- `known_object_names.yaml` : si de nouveaux noms ALL_CAPS sont introduits dans `templates/fabric/`, les ajouter à ce fichier
