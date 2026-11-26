"""Messages destinés aux personnes (erreurs et avertissements), en FR, EN et ES."""

from __future__ import annotations

from typing import Any

MESSAGES: dict[str, dict[str, str]] = {
    # Erreurs
    "unsupported_type": {
        "fr": "Ce type de fichier n'est pas pris en charge. Choisis un document Word (.docx) "
        "ou un PDF.",
        "en": "This file type is not supported. Choose a Word (.docx) document or a PDF.",
        "es": "Este tipo de archivo no es compatible. Elige un documento Word (.docx) o un PDF.",
    },
    "old_word": {
        "fr": "Les anciens fichiers .doc ne sont pas pris en charge. Ouvre-le dans Word ou "
        "LibreOffice et enregistre-le en .docx.",
        "en": "Old .doc files are not supported. Open it in Word or LibreOffice and save it "
        "as .docx.",
        "es": "Los archivos .doc antiguos no son compatibles. Ábrelo en Word o LibreOffice y "
        "guárdalo como .docx.",
    },
    "bad_content": {
        "fr": "Le contenu du fichier ne correspond pas à un document {kind} valide. Il est "
        "peut-être endommagé.",
        "en": "The file content is not a valid {kind} document. It may be damaged.",
        "es": "El contenido del archivo no es un documento {kind} válido. Puede estar dañado.",
    },
    "encrypted": {
        "fr": "Ce document est protégé par un mot de passe. Retire la protection puis réessaie.",
        "en": "This document is password protected. Remove the protection and try again.",
        "es": "Este documento está protegido con contraseña. Quita la protección y reintenta.",
    },
    "too_big": {
        "fr": "Ce fichier dépasse la taille maximale autorisée ({max} Mo). Tu peux la changer "
        "dans les réglages.",
        "en": "This file is larger than the allowed maximum ({max} MB). You can change it in "
        "Settings.",
        "es": "Este archivo supera el tamaño máximo permitido ({max} MB). Puedes cambiarlo en "
        "Ajustes.",
    },
    "empty_file": {
        "fr": "Ce fichier est vide.",
        "en": "This file is empty.",
        "es": "Este archivo está vacío.",
    },
    "not_found": {
        "fr": "Fichier introuvable. Il a peut-être été déplacé ou supprimé.",
        "en": "File not found. It may have been moved or deleted.",
        "es": "Archivo no encontrado. Puede haberse movido o eliminado.",
    },
    "nothing_to_do": {
        "fr": "Choisis un format de sortie différent ou active la traduction.",
        "en": "Choose a different output format or turn translation on.",
        "es": "Elige otro formato de salida o activa la traducción.",
    },
    "same_language": {
        "fr": "La langue de départ et la langue d'arrivée doivent être différentes.",
        "en": "Source and target languages must be different.",
        "es": "Los idiomas de origen y destino deben ser distintos.",
    },
    "busy": {
        "fr": "Une tâche est en cours : attends qu'elle soit terminée.",
        "en": "A task is running: wait until it finishes.",
        "es": "Hay una tarea en curso: espera a que termine.",
    },
    "bad_request": {
        "fr": "La demande n'est pas valide.",
        "en": "Invalid request.",
        "es": "La solicitud no es válida.",
    },
    "no_libreoffice": {
        "fr": "LibreOffice est nécessaire pour créer un PDF et n'a pas été trouvé. Installe-le "
        "depuis libreoffice.org (Windows : winget install TheDocumentFoundation.LibreOffice, "
        "macOS : brew install --cask libreoffice, Linux : sudo apt install libreoffice-writer), "
        "puis relance Iris.",
        "en": "LibreOffice is required to create a PDF and was not found. Install it from "
        "libreoffice.org (Windows: winget install TheDocumentFoundation.LibreOffice, macOS: "
        "brew install --cask libreoffice, Linux: sudo apt install libreoffice-writer), then "
        "restart Iris.",
        "es": "LibreOffice es necesario para crear un PDF y no se ha encontrado. Instálalo desde "
        "libreoffice.org (Windows: winget install TheDocumentFoundation.LibreOffice, macOS: "
        "brew install --cask libreoffice, Linux: sudo apt install libreoffice-writer) y "
        "reinicia Iris.",
    },
    "no_tesseract": {
        "fr": "Ce PDF est un scan : Tesseract OCR est nécessaire pour en lire le texte. "
        "Installe-le (Windows : winget install UB-Mannheim.TesseractOCR, macOS : brew install "
        "tesseract tesseract-lang, Linux : sudo apt install tesseract-ocr tesseract-ocr-fra "
        "tesseract-ocr-spa), puis relance Iris.",
        "en": "This PDF is a scan: Tesseract OCR is needed to read its text. Install it "
        "(Windows: winget install UB-Mannheim.TesseractOCR, macOS: brew install tesseract "
        "tesseract-lang, Linux: sudo apt install tesseract-ocr tesseract-ocr-fra "
        "tesseract-ocr-spa), then restart Iris.",
        "es": "Este PDF es un escaneado: se necesita Tesseract OCR para leer el texto. "
        "Instálalo (Windows: winget install UB-Mannheim.TesseractOCR, macOS: brew install "
        "tesseract tesseract-lang, Linux: sudo apt install tesseract-ocr tesseract-ocr-fra "
        "tesseract-ocr-spa) y reinicia Iris.",
    },
    "no_ocr_lang": {
        "fr": "Il manque des langues à Tesseract : {langs}. Ajoute les fichiers .traineddata "
        "correspondants dans {folder} ou réinstalle Tesseract avec ces langues.",
        "en": "Tesseract is missing languages: {langs}. Add the matching .traineddata files to "
        "{folder} or reinstall Tesseract with these languages.",
        "es": "A Tesseract le faltan idiomas: {langs}. Añade los archivos .traineddata en "
        "{folder} o reinstala Tesseract con esos idiomas.",
    },
    "scan_without_ocr": {
        "fr": "Ce PDF ne contient pas de texte (c'est un scan) et la reconnaissance de texte est "
        "désactivée dans les réglages.",
        "en": "This PDF contains no text (it is a scan) and text recognition is turned off in "
        "Settings.",
        "es": "Este PDF no contiene texto (es un escaneado) y el reconocimiento de texto está "
        "desactivado en Ajustes.",
    },
    "no_text": {
        "fr": "Aucun texte n'a pu être lu dans ce document.",
        "en": "No text could be read in this document.",
        "es": "No se ha podido leer texto en este documento.",
    },
    "no_model": {
        "fr": "Le modèle de langue {pairs} n'est pas installé. Va dans « Langues installées » "
        "pour le télécharger (une seule fois).",
        "en": "The language model {pairs} is not installed. Go to “Installed languages” to "
        "download it (only once).",
        "es": "El modelo de idioma {pairs} no está instalado. Ve a «Idiomas instalados» para "
        "descargarlo (solo una vez).",
    },
    "model_download": {
        "fr": "Le téléchargement du modèle a échoué. Vérifie ta connexion internet puis réessaie.",
        "en": "The model download failed. Check your internet connection and try again.",
        "es": "La descarga del modelo ha fallado. Comprueba tu conexión e inténtalo de nuevo.",
    },
    "convert_failed": {
        "fr": "La conversion a échoué. Le document utilise peut-être un élément non pris en "
        "charge.",
        "en": "The conversion failed. The document may use an unsupported feature.",
        "es": "La conversión ha fallado. Puede que el documento use un elemento no compatible.",
    },
    "timeout": {
        "fr": "La conversion a pris trop de temps et a été interrompue.",
        "en": "The conversion took too long and was stopped.",
        "es": "La conversión tardó demasiado y se detuvo.",
    },
    "write_failed": {
        "fr": "Impossible d'écrire dans le dossier {folder}. Choisis un autre dossier de sortie.",
        "en": "Cannot write to the folder {folder}. Choose another output folder.",
        "es": "No se puede escribir en la carpeta {folder}. Elige otra carpeta de salida.",
    },
    "unauthorized": {
        "fr": "Session expirée. Relance Iris puis utilise la nouvelle fenêtre.",
        "en": "Session expired. Restart Iris and use the new window.",
        "es": "Sesión caducada. Reinicia Iris y usa la nueva ventana.",
    },
    "internal": {
        "fr": "Une erreur inattendue s'est produite. Le détail est enregistré dans le journal.",
        "en": "An unexpected error occurred. Details were written to the log.",
        "es": "Se ha producido un error inesperado. El detalle está en el registro.",
    },
    # Avertissements du rapport de fidélité
    "w_untranslated": {
        "fr": "{count} paragraphe(s) n'ont pas pu être traduits et sont restés dans la langue "
        "d'origine.",
        "en": "{count} paragraph(s) could not be translated and were left in the original "
        "language.",
        "es": "{count} párrafo(s) no se pudieron traducir y quedan en el idioma original.",
    },
    "w_longer": {
        "fr": "Le texte traduit est {percent} % plus long : des sauts de ligne ou de page ont pu "
        "bouger. La taille des polices n'a pas été modifiée.",
        "en": "The translated text is {percent}% longer: line or page breaks may have moved. Font "
        "sizes were not changed.",
        "es": "El texto traducido es un {percent} % más largo: los saltos de línea o de página "
        "pueden haber cambiado. No se modificó el tamaño de letra.",
    },
    "w_pages": {
        "fr": "Le nombre de pages est passé de {before} à {after} : vérifie la mise en page.",
        "en": "The page count went from {before} to {after}: check the layout.",
        "es": "El número de páginas pasó de {before} a {after}: revisa el diseño.",
    },
    "w_mixed_style": {
        "fr": "{count} paragraphe(s) mélangeant plusieurs styles : le gras, l'italique ou les "
        "liens ont été replacés au mieux, à vérifier.",
        "en": "{count} paragraph(s) with mixed styles: bold, italics or links were placed as "
        "closely as possible, please check.",
        "es": "{count} párrafo(s) con estilos mezclados: negritas, cursivas o enlaces se "
        "colocaron lo mejor posible, revísalos.",
    },
    "w_pdf_rebuilt": {
        "fr": "Un PDF n'est pas fait pour être modifié : sa mise en page a été reconstruite et "
        "peut différer de l'original.",
        "en": "PDF is not an editable format: the layout was rebuilt and may differ from the "
        "original.",
        "es": "Un PDF no es un formato editable: el diseño se ha reconstruido y puede diferir "
        "del original.",
    },
    "w_pdf_roundtrip": {
        "fr": "Pour traduire ce PDF, il est passé par un document Word intermédiaire avant d'être "
        "recréé en PDF.",
        "en": "To translate this PDF, it went through an intermediate Word document before being "
        "recreated as PDF.",
        "es": "Para traducir este PDF, pasó por un documento Word intermedio antes de volver a "
        "crearse como PDF.",
    },
    "w_ocr": {
        "fr": "Document scanné : le texte a été reconnu automatiquement ({pages} page(s)). "
        "Images, tableaux et mise en forme d'origine ne sont pas conservés ; relis le résultat.",
        "en": "Scanned document: text was recognised automatically ({pages} page(s)). Original "
        "images, tables and formatting are not kept; proofread the result.",
        "es": "Documento escaneado: el texto se reconoció automáticamente ({pages} página(s)). "
        "No se conservan imágenes, tablas ni formato originales; revisa el resultado.",
    },
    "w_pages_without_text": {
        "fr": "{count} page(s) du PDF ne contiennent pas de texte lisible : leur contenu n'a pas "
        "été traduit.",
        "en": "{count} PDF page(s) have no readable text: their content was not translated.",
        "es": "{count} página(s) del PDF no tienen texto legible: su contenido no se tradujo.",
    },
    "w_pivot": {
        "fr": "Traduction en deux temps via l'anglais : qualité un peu inférieure aux paires "
        "directes.",
        "en": "Two-step translation through English: slightly lower quality than direct pairs.",
        "es": "Traducción en dos pasos a través del inglés: calidad algo inferior a la directa.",
    },
}


class _Safe(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return "?"


def message(code: str, lang: str = "fr", **params: Any) -> str:
    entry = MESSAGES.get(code, MESSAGES["internal"])
    return entry.get(lang, entry["fr"]).format_map(_Safe(params))


class IrisError(Exception):
    """Erreur prévue : un message clair pour la personne, un détail technique à part."""

    def __init__(self, code: str, detail: str = "", **params: Any) -> None:
        self.code = code
        self.detail = detail
        self.params = params
        super().__init__(message(code, **params))


class Cancelled(Exception):
    """La tâche a été annulée."""
