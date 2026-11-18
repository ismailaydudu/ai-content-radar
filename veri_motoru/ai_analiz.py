"""Gemini analizi; Sanity'ye baglanmaz ve veri yazmaz."""
import sys

from api_utils import ApiError, create_gemini_client, gemini_analiz_et, load_settings


def main():
    load_settings()
    ozet = (
        'Uzak bir hastaneye paket götürmekle görevlendirilen talihsiz bir kurye, '
        'vardığında kendini bir salgının ortasında bulur ve hayatta kalmaya çalışır.'
    )
    with create_gemini_client() as client:
        veri = gemini_analiz_et(client, ozet)
    print('Yapay zeka analizi tamamlandi.')
    print(f"Hedef kitle: {veri['hedef_kitle']}")
    print(f"3 kelime: {veri['uc_kelime']}")
    print(f"Radar skoru: {veri['skor']}")


if __name__ == '__main__':
    try:
        main()
    except ApiError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
