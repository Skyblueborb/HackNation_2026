/** Pure form/document logic. No React, no DOM — safe to unit-test. */

import type { ExtractedFile } from './utils/zip';

export interface OdwolanieKioFields {
  data: string;
  czynnosc_dzien: string;
  czynnosc_powod_id: string;
  czynnosc_opis: string;
  miejscowosc: string;
}

export interface OdwolujacyFields {
  krs: string;
  nazwa: string;
  nip: string;
  regon: string;
  przez_pelnomocnika: string; // "1" lub "0"
  pelnomocnik_imie_nazwisko: string;
  pelnomocnik_nazwa: string;
  pelnomocnik_mail: string;
}

export interface ZamawiajacyFields {
  krs: string;
  nazwa: string;
  nip: string;
  regon: string;
  prowadzacy_postepowanie: string; // "null" | "1" | "0"
}

export interface ZamowieniePubliczneFields {
  numer_bzp: string;
  numer_postepowania: string;
  numer_ted: string;
  tytul: string;
}

export interface OdwolanieFormData {
  OdwolanieKIO: OdwolanieKioFields;
  Odwolujacy: OdwolujacyFields;
  Zamawiajacy: ZamawiajacyFields;
  ZamowieniePubliczne: ZamowieniePubliczneFields;
}

export interface PelnomocnictwoMocodawcaFields {
  imie_nazwisko: string;
  krs: string;
  nazwa: string;
  nip: string;
  typ: 'osoba_prawna' | 'osoba_fizyczna';
  podpisujacy_imie_nazwisko: string;
}

export interface PelnomocnikFields {
  imie_nazwisko: string;
  pesel: string;
}

export interface PelnomocnictwoFormData {
  mocodawca: PelnomocnictwoMocodawcaFields;
  pelnomocnicy: PelnomocnikFields;
}

export interface PrzelewBankowyFields {
  data_operacji: string;
  kwota: string;
  na_rachunek: string;
  numer_transakcji: string;
  tytul: string;
  z_rachunku: string;
}

export interface PrzelewFormData {
  przelew_bankowy: PrzelewBankowyFields;
}

export type DocClass = 'odwolanie' | 'pelnomocnictwo' | 'przelew';

export interface FormBundle {
  odwolanie: OdwolanieFormData;
  pelnomocnictwo: PelnomocnictwoFormData;
  przelew: PrzelewFormData;
}

export interface DocumentSlot {
  id: string;              // client_doc_id — unikalny dla jednego pliku z ZIP-a
  doc_class: DocClass;     // typ tego konkretnego pliku
  title: string;
  categoryLabel: string;
  defaultFilename: string;
  sourceName: string;
  file?: ExtractedFile;
  data: FormBundle;        // dane dla każdego typu — zmiana typu nic nie kasuje
}

export const CLASS_LABEL: Record<DocClass, string> = {
  odwolanie: 'Odwołanie',
  pelnomocnictwo: 'Pełnomocnictwo',
  przelew: 'Przelew',
};

export function newDocId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function emptyForms(): FormBundle {
  return {
    odwolanie: {
      OdwolanieKIO: { data: '', czynnosc_dzien: '', czynnosc_powod_id: '', czynnosc_opis: '', miejscowosc: '' },
      Odwolujacy: { krs: '', nazwa: '', nip: '', regon: '', przez_pelnomocnika: '1', pelnomocnik_imie_nazwisko: '', pelnomocnik_nazwa: '', pelnomocnik_mail: '' },
      Zamawiajacy: { krs: '', nazwa: '', nip: '', regon: '', prowadzacy_postepowanie: 'null' },
      ZamowieniePubliczne: { numer_bzp: '', numer_postepowania: '', numer_ted: '', tytul: '' },
    },
    pelnomocnictwo: {
      mocodawca: { imie_nazwisko: '', krs: '', nazwa: '', nip: '', typ: 'osoba_prawna', podpisujacy_imie_nazwisko: '' },
      pelnomocnicy: { imie_nazwisko: '', pesel: '' },
    },
    przelew: {
      przelew_bankowy: { data_operacji: '', kwota: '', na_rachunek: '60 1010 1010 0081 3622 3100 0000', numer_transakcji: '', tytul: '', z_rachunku: '' },
    },
  };
}

export function makeDoc(docClass: DocClass, n: number, file?: ExtractedFile, sourceName?: string): DocumentSlot {
  const name = sourceName ?? `${docClass}.pdf`;
  return {
    id: newDocId(),
    doc_class: docClass,
    title: `${CLASS_LABEL[docClass]} #${n}`,
    categoryLabel: CLASS_LABEL[docClass],
    defaultFilename: name,
    sourceName: name,
    file,
    data: emptyForms(),
  };
}

export function defaultDocs(): DocumentSlot[] {
  return [makeDoc('odwolanie', 1), makeDoc('pelnomocnictwo', 1), makeDoc('przelew', 1)];
}

/** Klasyfikacja pliku po nazwie — każdy plik to osobny byt. */
export function classifyName(name: string): DocClass {
  const n = name.toLowerCase();
  if (n.includes('odwol') || n.includes('appeal') || n.includes('odwoł')) return 'odwolanie';
  if (n.includes('pelnom') || n.includes('pełnom') || n.includes('power')) return 'pelnomocnictwo';
  if (n.includes('przel') || n.includes('przelew') || n.includes('trans') || n.includes('platn')) return 'przelew';
  return 'odwolanie';
}

/**
 * Klasa z odpowiedzi LLM. Backend używa `potwierdzenie_przelewu`, frontend
 * `przelew`. Zwraca null, gdy wartość jest nieznana — wtedy zostaje nazwa pliku.
 */
export function classFromLlm(value: unknown): DocClass | null {
  if (value === 'odwolanie' || value === 'pelnomocnictwo' || value === 'przelew') return value;
  if (value === 'potwierdzenie_przelewu') return 'przelew';
  return null;
}

/** Numeruje tytuły w kolejności klas po zmianie typu dowolnego dokumentu. */
export function renumberTitles(slots: DocumentSlot[]): DocumentSlot[] {
  const counters: Record<DocClass, number> = { odwolanie: 0, pelnomocnictwo: 0, przelew: 0 };
  return slots.map((d) => {
    counters[d.doc_class]++;
    return {
      ...d,
      title: `${CLASS_LABEL[d.doc_class]} #${counters[d.doc_class]}`,
      categoryLabel: CLASS_LABEL[d.doc_class],
    };
  });
}

/** "10 000,50" / "10000.50" -> 10000.5. Białe znaki znika przed przecinkiem. */
export function parseAmount(raw: string): number | null {
  const normalized = raw.replace(/\s+/g, '').replace(',', '.');
  return normalized ? parseFloat(normalized) : null;
}

/** Czysta funkcja: zwraca kanoniczny JSON dla dowolnego dokumentu. */
export function buildCanonical(docClass: DocClass, data: FormBundle) {
  if (docClass === 'odwolanie') {
    const { OdwolanieKIO, Odwolujacy, Zamawiajacy, ZamowieniePubliczne } = data.odwolanie;
    return {
      OdwolanieKIO: {
        data: OdwolanieKIO.data || null,
        czynnosc_dzien: OdwolanieKIO.czynnosc_dzien || null,
        czynnosc_powod_id: OdwolanieKIO.czynnosc_powod_id ? parseInt(OdwolanieKIO.czynnosc_powod_id) : null,
        czynnosc_opis: OdwolanieKIO.czynnosc_opis || null,
        miejscowosc: OdwolanieKIO.miejscowosc || null,
      },
      Odwolujacy: [{
        krs: Odwolujacy.krs || null,
        nazwa: Odwolujacy.nazwa || null,
        nip: Odwolujacy.nip || null,
        regon: Odwolujacy.regon || null,
        'przez-pelnomocnika': Odwolujacy.przez_pelnomocnika === '1' ? 1 : 0,
        pelnomocnik: Odwolujacy.pelnomocnik_imie_nazwisko
          ? {
              imie_nazwisko: Odwolujacy.pelnomocnik_imie_nazwisko,
              nazwa: Odwolujacy.pelnomocnik_nazwa || null,
              mail: Odwolujacy.pelnomocnik_mail || null,
            }
          : null,
      }],
      Zamawiajacy: [{
        krs: Zamawiajacy.krs || null,
        nazwa: Zamawiajacy.nazwa || null,
        nip: Zamawiajacy.nip || null,
        regon: Zamawiajacy.regon || null,
        prowadzacy_postepowanie:
          Zamawiajacy.prowadzacy_postepowanie === '1'
            ? 1
            : Zamawiajacy.prowadzacy_postepowanie === '0'
            ? 0
            : null,
      }],
      ZamowieniePubliczne: {
        numer_bzp: ZamowieniePubliczne.numer_bzp || null,
        numer_postepowania: ZamowieniePubliczne.numer_postepowania || null,
        numer_ted: ZamowieniePubliczne.numer_ted || null,
        tytul: ZamowieniePubliczne.tytul || null,
      },
    };
  }
  if (docClass === 'pelnomocnictwo') {
    const { mocodawca, pelnomocnicy } = data.pelnomocnictwo;
    return {
      mocodawca: [{
        data: {
          imie_nazwisko: mocodawca.typ === 'osoba_fizyczna' ? (mocodawca.imie_nazwisko || null) : null,
          krs: mocodawca.krs || null,
          nazwa: mocodawca.nazwa || null,
          nip: mocodawca.nip || null,
          typ: mocodawca.typ,
        },
        podpisujacy: mocodawca.podpisujacy_imie_nazwisko
          ? [{ imie_nazwisko: mocodawca.podpisujacy_imie_nazwisko }]
          : [],
      }],
      pelnomocnicy: [{
        imie_nazwisko: pelnomocnicy.imie_nazwisko || null,
        pesel: pelnomocnicy.pesel ? (isNaN(Number(pelnomocnicy.pesel)) ? pelnomocnicy.pesel : Number(pelnomocnicy.pesel)) : null,
      }],
    };
  }
  const { przelew_bankowy } = data.przelew;
  return {
    przelew_bankowy: {
      data_operacji: przelew_bankowy.data_operacji || null,
      kwota: parseAmount(przelew_bankowy.kwota),
      na_rachunek: przelew_bankowy.na_rachunek.replace(/\s+/g, '') || null,
      numer_transakcji: przelew_bankowy.numer_transakcji || null,
      tytul: przelew_bankowy.tytul || null,
      z_rachunku: przelew_bankowy.z_rachunku.replace(/\s+/g, '') || null,
    },
  };
}
