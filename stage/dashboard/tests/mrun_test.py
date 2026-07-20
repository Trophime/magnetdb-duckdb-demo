from python_magnetrun.MagnetRun import load_mrun

#magnet = load_mrun("2025.01.24 - 10:30:29.txt","M9")
magnet = load_mrun("M9_Archive_251202-1430.tdms","M9")
#print(magnet.MagnetData.Groups['Infos'])

# Dans un autre composant de votre layout (ex: un dcc.Markdown ou une html.Div)
def afficher_infos_supplementaires(mrun):
    infos = mrun.MagnetData.Groups.get('Infos', {})
    # Transforme le dictionnaire en texte lisible
    texte = "\n".join([f"- {k}: {v}" for k, v in infos.items()])
    return texte



def get_magnet_infos(mrun):
    """Extrait les métadonnées du groupe 'Infos' sous forme de dictionnaire ou de texte."""
    infos = mrun.MagnetData.Groups.get('Infos', {})
    return infos

print("Tous les groupes disponibles :", magnet.MagnetData.Groups.keys())

