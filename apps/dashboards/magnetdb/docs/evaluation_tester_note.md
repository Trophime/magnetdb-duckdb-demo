# Évaluation du dashboard MagnetDB — note pour les testeurs

Merci de participer à l'évaluation du dashboard MagnetDB. Cette note explique
comment y accéder (une configuration de quelques minutes, une seule fois), quoi
tester, et comment signaler un problème.

Période de test : **[à compléter]**

## Ce que vous testez

- Le dashboard MagnetDB en **lecture seule** : rien de ce que vous faites ne
  modifie les données. Les réglages d'affichage (langue, style des courbes)
  sont gardés dans votre navigateur uniquement.
- Base de données : une **copie figée au 8 octobre 2026** (6483 expériences,
  23 aimants, 58 assemblages).
- Fichiers de mesure (pupitre, TDMS, archives) : l'arborescence réelle, en
  lecture seule.

## Avant de commencer (une seule fois)

### 1. Réseau

Connectez-vous depuis un poste du **réseau filaire du LNCMI**. Depuis le VPN,
le site n'est pas joignable pour le moment.

### 2. Certificat

Le site utilise un certificat signé par une autorité de certification (AC)
interne. Vous avez reçu son certificat public, `rootCA.pem`, avec cette note.
Deux possibilités :

**Recommandé : importer `rootCA.pem`**, après avoir vérifié son empreinte.
Elle doit être exactement :

| Empreinte | Valeur |
|---|---|
| SHA-256 | `77:62:6E:7F:81:74:F2:CA:63:F4:A3:8E:BE:15:62:59:22:D2:05:CA:BC:E4:7D:25:5C:38:34:BB:91:05:B1:B3` |
| SHA-1 (affichée par Windows) | `3D:91:57:DB:1A:09:6B:35:49:1A:A3:8F:FF:63:28:09:43:5C:19:56` |

Si l'empreinte ne correspond pas, n'importez pas le fichier et prévenez-moi.

- **Firefox** (toutes plateformes ; c'est le plus simple et cela ne touche que
  Firefox) : Paramètres → Vie privée et sécurité → Certificats → *Afficher
  les certificats…* → onglet *Autorités* → *Importer…* → choisir `rootCA.pem`.
  Dans la fenêtre qui s'ouvre, *Voir* permet de comparer l'empreinte SHA-256,
  puis cochez **uniquement** « Confirmer cette AC pour identifier des sites
  web » → OK.
- **Chrome ou Edge sous Windows** : renommez le fichier en `rootCA.crt`,
  double-cliquez dessus, vérifiez l'empreinte (onglet *Détails* → *Empreinte
  numérique*, c'est la SHA-1), puis *Installer le certificat…* → *Utilisateur
  actuel* → « Placer tous les certificats dans le magasin suivant » →
  *Autorités de certification racines de confiance* → *Terminer*, et
  confirmez l'avertissement de sécurité. Redémarrez le navigateur.
- **Chrome ou Chromium sous Linux** (paquet `libnss3-tools`) :
  ```bash
  openssl x509 -in rootCA.pem -noout -fingerprint -sha256   # vérifier l'empreinte
  certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n "MagnetDB evaluation CA" -i rootCA.pem
  ```
  puis redémarrez le navigateur.

> Une AC importée peut garantir n'importe quel site, pas seulement celui-ci :
> retirez-la à la fin de l'évaluation (voir [Après l'évaluation](#après-lévaluation)).

**Plus simple : accepter l'avertissement.** Sans import, le navigateur affiche
un avertissement de sécurité à la première visite. Pour ce serveur interne
uniquement, vous pouvez passer outre : Firefox → *Avancé…* → *Accepter le
risque et poursuivre* (retenu ensuite) ; Chrome/Edge → *Paramètres avancés* →
*Continuer vers le site calcul18.lncmig.local (dangereux)* (redemandé à chaque
session).

### 3. Identifiant

Un compte partagé : identifiant **`tester`**. Le mot de passe vous est
communiqué séparément ; ne le transmettez à personne et ne l'écrivez jamais
dans un ticket.

## Ouvrir le dashboard

**<https://calcul18.lncmig.local:8443/>**

Le navigateur demande l'identifiant et le mot de passe, puis le dashboard
s'affiche.

| Symptôme | Cause probable |
|---|---|
| « Adresse introuvable » ou délai dépassé | Pas sur le réseau filaire du LNCMI, ou sur le VPN |
| Avertissement de sécurité | Certificat non importé (voir étape 2) |
| La demande de mot de passe revient sans cesse | Identifiant ou mot de passe erroné |
| « 404 page not found » | Adresse mal saisie : vérifiez `https://` et `:8443` |

## Quoi tester

En haut de chaque page : la liste **Base de données :** (une seule base pour
cette évaluation) et le bouton **🌐** pour changer de langue (English,
Français, Deutsch, Nederlands).

Parcourez chaque page du menu ; pour chacune, notez ce qui manque, ce qui est
faux, lent ou peu clair.

| Page | À essayer |
|---|---|
| **Manips** | Expériences et manips par domaine de recherche ; filtres par site et par année |
| **Sites** | Page d'accueil : activité de mise en service par mois, énergie et temps aimant par site |
| **Assemblages** | Énergie et temps aimant par assemblage ; filtre par site |
| **Aimants** | Choisir un aimant : historique de ses assemblages et de ses pièces, temps aimant ; filtre par statut |
| **Pièces** | Choisir une pièce : historique de ses aimants et de ses assemblages (pas d'historique de contrainte orthoradiale dans cette copie) |
| **Visualiseur de fichiers** | Afficher un fichier pupitre, un fichier TDMS et un fichier d'archive ; zoomer, puis double-cliquer pour revenir à la vue complète ; le bouton **⚙** d'un groupe de courbes pour changer leur style |
| **Enregistrements de synthèse** | Choisir un enregistrement (filtres site, année, statut, assemblage), cocher des capteurs pour afficher leurs courbes ; un clic sur une courbe pose un curseur ; bouton **⚙** comme ci-dessus |
| **Défauts et pics** | Choisir un enregistrement puis un défaut ou un pic, cocher un capteur pour afficher sa courbe |
| **Pigbrother Stats viewer** | Choisir un fichier de statistiques Pigbrother et l'axe des abscisses (titre non traduit) |
| **À propos** | Journal des opérations sur la base, avec filtres par table, opération, statut et date |

À vérifier aussi :

- un changement de langue avec **🌐** puis *Save* : la page se recharge dans
  la nouvelle langue ;
- un changement de style avec **⚙** : il doit être conservé après un
  rechargement de la page (il est enregistré dans votre navigateur).

## Signaler un problème ou une suggestion

Les retours se font par **tickets GitHub** sur le dépôt
[Trophime/magnetdb-duckdb-demo](https://github.com/Trophime/magnetdb-duckdb-demo/issues).

> **Le dépôt est public : tout le monde peut lire les tickets.** N'y mettez
> jamais le mot de passe, ni de capture d'écran montrant des données, ni de
> valeurs ou d'acronymes d'utilisateurs. Si une capture est utile, recadrez ou
> floutez les données. Si un détail sensible est indispensable, écrivez-le
> dans le ticket (« détail envoyé par courriel ») et envoyez-le par courriel
> à Christophe Trophime.

Créer un ticket :

1. Connectez-vous à [GitHub](https://github.com/login) (ou créez un compte
   gratuit).
2. Ouvrez le **[formulaire de ticket](https://github.com/Trophime/magnetdb-duckdb-demo/issues/new?template=dashboard.yml)**.
3. Complétez le titre après « [Dashboard] » en quelques mots
   (ex. « [Dashboard] Visualiseur : courbe vide pour un fichier TDMS »).
4. Remplissez le formulaire. Sont obligatoires : la page, ce que vous avez
   fait, ce qui s'est passé, et **la date et l'heure à la minute** : avec un
   compte partagé, c'est le seul moyen de retrouver votre visite dans les
   journaux du serveur.
5. Relisez : rien de sensible ? Puis *Create* (*Créer*).
6. Si l'on vous demande des précisions, répondez dans le même ticket.

Un ticket par problème ou suggestion, s'il vous plaît.

## Limites connues

- Données figées au 8 octobre 2026 : les expériences plus récentes
  n'apparaissent pas.
- Pas d'historique de contrainte orthoradiale (page *Pièces*).
- La première ouverture d'un gros fichier de mesure peut prendre quelques
  secondes.
- Site inaccessible depuis le VPN pour le moment.

## Après l'évaluation

- **Retirez l'AC** si vous l'avez importée :
  - Firefox : Paramètres → Vie privée et sécurité → Certificats → *Afficher
    les certificats…* → *Autorités* → « mkcert development CA » →
    *Supprimer ou ne plus faire confiance…* ;
  - Windows : lancez `certmgr.msc` → *Autorités de certification racines de
    confiance* → *Certificats* → « mkcert christophe.trophime@… » →
    *Supprimer* ;
  - Linux :
    `certutil -d sql:$HOME/.pki/nssdb -D -n "MagnetDB evaluation CA"`.
- Le mot de passe du compte `tester` sera changé à la fin de l'évaluation.
