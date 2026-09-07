# UX2_PROJECT.md — suivi de la migration UX1 → UX2

Liste de suivi du projet nac4. Tenir à jour à chaque session : cocher ce qui est
fait, déplacer entre sections, et **noter la preuve** (message d'erreur, apply,
sortie de contrôle) plutôt que « vérifié ».

`AGENTS.md` reste la référence des règles et des mécanismes. Ce document-ci ne
porte que l'état d'avancement.

**Dernière mise à jour : 2026-09-04**

---

## État actuel

| | BXT (branch-a-routed) | CML (branch-b-routed) | BEL (dc) |
|---|---|---|---|
| Généré | ✅ | ✅ | ✅ |
| `terraform apply` (objets vManage) | ✅ | ✅ | ✅ |
| Poussé sur les équipements | ❌ | ❌ | ❌ |

Les trois sites existent en vManage. **Aucune configuration n'est descendue sur
un équipement** : `configuration_group_deploy` et `policy_group_deploy` sont à
`false` pour les six routeurs (`generate.py` les émet ainsi ; les basculer est
une action délibérée, par déploiement).

La dernière configuration réellement présente sur un équipement est celle de
`bxtdw01` au 2026-08-28 (`DATA/generated_conf`), antérieure à tout le travail
Application Priority.

---

## 1. Données à renseigner (bloquent le déploiement)

- [ ] `globals.yaml` — `commvault.sin_server_prefixes` (CIDR réel)
- [ ] `globals.yaml` — `commvault.server_prefixes`
- [ ] `globals.yaml` — `backup.server_prefixes`
- [ ] `globals.yaml` — `qos_hosts.tube_server_prefixes`
- [ ] `globals.yaml` — `qos_hosts.scavenger_host_prefixes`
- [ ] `templates/_shared/system.yaml` — `SNMP_USERNAME_1`, `SNMP_USERNAME_2`
- [ ] `templates/_shared/system.yaml` — `SNMP_AUTH_PASSWORD`, `SNMP_PRIV_PASSWORD`
- [ ] `templates/{branch,dc}/aaa_tacacs.yaml` — `TACACS_ENCRYPTED_KEY`
- [ ] `values/bxt.yaml` — `OSPF_MD5_KEY`
- [ ] `values/bel.yaml` — `vpn512_desc` manquant sur les 2 routeurs (seul échec
      `validate_model.py` restant)
- [ ] `values/bel.yaml` — chassis_id, IP, AS BGP encore placeholders
- [ ] `values/cml.yaml` — chassis_id, hostnames, IP, interfaces encore ceux de BXT
- [x] `known_object_names.yaml` — ajouter `FABRIC_SECURITY` (faux positif du scan :
      chaîne de description dans `system.yaml:64`, pas une valeur à remplir)

## 2. Prochaine étape — le déploiement

- [ ] Basculer `configuration_group_deploy` / `policy_group_deploy` à `true`
      sur un site pilote, après avoir renseigné la section 1
- [ ] Comparer la running-config obtenue à `DATA/valid_conf` (référence UX1)
- [ ] Vérifier que les class-maps et le `policy-map` QoS apparaissent
      (absents de `DATA/generated_conf` au 2026-08-28)
- [ ] Vérifier le rendu des route-maps `OMP_TO_BGP_1000_MED*` et des
      `ip prefix-list LO_BB_PFX-<SITE>`
- [ ] Vérifier que la default OMP arrive bien sur les spokes et repart en BGP
      avec MED 1000 vers le SDA border

## 3. À confirmer en exploitation

- [ ] `TRAFFIC-<SITE>` en direction `all` — observer le comportement AAR sur le
      trafic venant du tunnel (effet de bord accepté lors de la fusion)
- [ ] `policy_object_profile` sur le config group est-il nécessaire pour que le
      device rende `ip prefix-list` ? (jamais testé sans)
- [ ] Confirmer la règle `protocol ∈ {network, aggregate} ⟺ liste de préfixes`,
      puis la transformer en check (déduite d'un seul refus, un seul cas positif)
- [ ] Fermer les `TODO: verify` restants contre la source du module :
      `templates/dc/transport.yaml`, `templates/branch/cli.yaml`,
      `templates/branch/service.yaml`

## 4. Décisions à arbitrer

- [ ] Contradiction Commvault — `COMMVAULT_SIN_TO_SERVERS` porte
      `local_tloc custom2/custom1` **et** `preferred_colors private`. Héritée
      d'UX1, conservée par choix de reproduction stricte
- [ ] `LO_Teams_Video-<SITE>` déclaré mais plus référencé depuis la fusion
      (couvert par `LO_Business_MM_Conf_V2`) — garder ou supprimer
- [ ] Renommer `values/aar/` (porte toute la traffic policy, plus seulement l'AAR)
- [ ] Raccourcir `LO_Business_MM_Streaming_V2` et `LO_Business_Transac_Data_V2`
      (31 car.) — sous la limite de 32 aujourd'hui, cassent dès qu'un code site
      dépasse 3 lettres
- [ ] Commentaires TLOC-EXT de `transport-a.yaml` (« private1 sur r1 / private2
      sur r2 ») en désaccord avec les valeurs réelles de BXT (private1 partout
      en physique, private2 partout en tunnel) — aligner l'un sur l'autre
- [ ] BEL — `vpn512_desc` : ajouter la variable ou retirer sa référence du parcel

## 5. Dettes assumées, documentées

- [ ] DSCP 32 — seule divergence résiduelle de la fusion des deux policies UX1
      (détail dans `values/aar/_README.md`)
- [ ] `BACKUP_TO_COMMVAULT` — le match source d'UX1 était anonymisé
      `<IPNETWORK>` ; la règle est plus large qu'en production

## 6. Code quality / nice-to-have

- [ ] `--site` de `generate.py` matche le stem du fichier (ex. `bxt`) plutôt que
      le `site_code` YAML (ex. `BXT`) — help text trompeur ; aligner les deux
      ou corriger le help
- [ ] Lock-file : `providers.tf` conseille de commiter `.terraform.lock.hcl`,
      mais `sites/` est gitignor��e et régénérée — plutôt épingler la version du
      provider dans `root-template/providers.tf` lui-même
- [ ] `RENAME_MAP` dans `csv_to_values.py` : plusieurs colonnes convergent vers
      `vpn0_default_route` (last-write-wins silencieux) — ajouter un assert qui
      avertit quand deux colonnes écrivent des valeurs différentes sur la même clé
- [ ] `requirements.txt` non pincé (`PyYAML>=6.0`) — épingler au moins une borne
      majeure pour la reproductibilité
- [ ] Pas d'entry point de validation globale : un mode `--check` sur `generate.py`
      (unicité `site_id`, scan placeholders, clés `__GLOBAL:` résolvables, tous les
      fichiers `VARIANTS` présents sur disque) rendrait un CI trivial
- [ ] `templates/branch/transport-b.yaml` — son jeu de variables est une hypothèse
      (branch-a moins MPLS/TLOC-EXT) ; vérifier contre un export réel branch-b
      (CML est le premier site réel de cette variante)

## 7. Hors périmètre / différé

- [ ] `sites/fabric/` — à recadrer autour de cflowd + control policies NYC/NYD.
      L'export ne contient aucun hub-and-spoke, et aucun de ces objets ne
      concerne BEL/BXT/CML
- [ ] `OSPF_TO_OMP_DNEY_DEFAULT`
- [ ] `OMP_TO_BGP_2000_MED`
- [ ] DC — port-channel LACP réel du LAG campus, serveurs AAA/radius réels,
      adressage transport DC dérivé et non exporté

---

## Acquis

### Sites

- [x] **BXT appliqué** — 2026-09-04
- [x] **CML appliqué** — 2026-09-04. Première mise en œuvre réelle de la
      variante `branch-b-routed`
- [x] **BEL appliqué** — 2026-09-04. Première mise en œuvre réelle de la
      variante `dc`

### Fermés par l'apply des trois sites

- [x] **La règle d'unicité tenant-wide des noms de parcels ne s'applique PAS à
      tous les types.** CML a créé `SYS-CML` avec ses parcels `global` / `omp`
      alors que BXT portait déjà les mêmes noms. Le suffixe `-<SITE>` reste
      donc requis pour les **policy objects** uniquement (PPARC0012, 2026-08-19),
      pas pour l'ensemble du dépôt.
- [x] **Les noms de route-maps ne nécessitent PAS de suffixe `-<SITE>`.** BXT et
      CML ont tous les deux été appliqués avec `OMP_TO_BGP_1000_MED` et
      `OMP_TO_BGP_1000_MED_ASPATH_PREPEND_BB` sans conflit PPARC0012 —
      confirmé 2026-09-07.
- [x] **`route_policies[]` `base_action` / `default_action`** — acceptés par
      vManage. Le rendu du route-map sur l'équipement reste à vérifier (§2)
- [x] **`qos_policies[].target_interfaces` peut rester vide** — accepté
- [x] **`ipv4_omp_advertise_routes` avec `protocol: network`** — accepté

### Règles établies sur erreurs réelles

- [x] **Limite de 32 caractères** sur les noms de parcels, suffixe compris
      (`SCHVALID0001 Invalid Format Attributes: name`, 2026-09-04). Budget :
      28 caractères pour le nom de base avec un code site à 3 lettres
- [x] **Noms de parcels uniques à l'échelle du tenant** pour les policy objects
      (`PPARC0012`, 2026-08-19) — d'où le suffixe `-<SITE>`
- [x] **Deux traffic policies ne peuvent pas se recouvrir sur (VPN, direction)**
      (`PPARC0008`, 2026-09-04), et `all` englobe `service`. D'où la fusion des
      deux policies UX1 en une seule, `TRAFFIC-<SITE>`
- [x] **Un profil réparti sur plusieurs fichiers : un seul déclare ses scalaires.**
      Un `description` contradictoire empêche la fusion et fait échouer le plan
      sur une clé `for_each` dupliquée (2026-09-04, BEL)
- [x] **Une variable de device doit être déclarée par un parcel**, sinon le PUT
      du config group est rejeté (`Not Defined In Schema Attributes`, 2026-09-04)
- [x] **Valide côté provider ≠ valide côté vManage.** L'énumération du provider
      est l'union de ce que le champ peut porter selon la forme ; vManage impose
      la forme (`ompProtocol`, 2026-09-04)

### Migration fonctionnelle

- [x] Application Priority — scheduler QoS (`LO_QOSMAP` V1 / V2)
- [x] Classification QoS — data policies `BXS-BXT_QOSClass_V5` / `LO_QOSClass_V3`
- [x] App-aware routing — `LO_AAR`, 9 séquences UX1 reproduites strictement
- [x] `fallback_to_best_path` et compteur `LO_COMMVAULT_Count` repris d'UX1
- [x] Objets de policy — forwarding classes, SLA classes, application lists,
      data prefix lists
- [x] Origination de la default OMP depuis le hub BEL vers les spokes
- [x] Dédoublonnage des objets DC (4 classes en double sur les mêmes queues)

### Outillage

- [x] Schéma du module lu, plus deviné — source disponible sous
      `sites/*/.terraform/modules/sdwan/`
- [x] `generate.py` — erreur dure sur collision de basename entre templates
- [x] `generate.py` — `values/aar/<site>.yaml` obligatoire par site
- [x] `validate_model.py` check 7 — longueur des noms de parcels
- [x] `validate_model.py` check 8 — clés absentes de la source du module
- [x] `validate_model.py` check 9 — scalaires contradictoires entre fichiers
- [x] `validate_model.py` check 3 — corrigé : lit les `{{var}}` des add-ons CLI
      (5 faux positifs par site supprimés, 2 vrais manques révélés sur CML)

---

## Méthode

Le mode d'échec dominant de cette migration est l'erreur **qui n'apparaît qu'à
l'apply**, jamais au plan : vManage nomme le champ fautif mais jamais la règle.
La démarche qui a fonctionné à chaque fois est de **comparer ce qui échoue à ce
qui passe** dans le même apply, et d'isoler la propriété qui les sépare.

`validate_model.py` couvre maintenant quatre classes de ces erreurs en amont.
**Le lancer avant chaque plan** — le check 8 exige un `terraform init` préalable
dans un root de site, sinon il se signale comme sauté.

```bash
python3 generate.py
python3 validate_model.py
cd sites/<site>/ && terraform plan -out=tfplan
```
