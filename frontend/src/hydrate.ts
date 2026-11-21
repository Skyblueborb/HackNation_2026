/**
 * Mapuje kanoniczny JSON z backendu na trzy obiekty formularza.
 * Kosmetyczny mostek — nie zmienia struktury App.tsx ani wyglądu.
 */

type Doc = { doc_class: string; canonical_json: any };

const s = (v: unknown): string => (v === null || v === undefined ? '' : String(v));

export function hydrateForms(docs: Doc[]): {
  odwolanie: any | null;
  pelnomocnictwo: any | null;
  przelew: any | null;
} {
  let odwolanie: any = null;
  let pelnomocnictwo: any = null;
  let przelew: any = null;

  for (const doc of docs) {
    const c = doc.canonical_json || {};

    if (doc.doc_class === 'odwolanie') {
      const kio = c.OdwolanieKIO || {};
      const odw = (c.Odwolujacy || [])[0] || {};
      const pel = odw.pelnomocnik || {};
      const zam = (c.Zamawiajacy || [])[0] || {};
      const zp = c.ZamowieniePubliczne || {};
      odwolanie = {
        OdwolanieKIO: {
          data: s(kio.data),
          czynnosc_dzien: s(kio.czynnosc_dzien),
          czynnosc_powod_id: s(kio.czynnosc_powod_id),
          czynnosc_opis: s(kio.czynnosc_opis),
          miejscowosc: s(kio.miejscowosc),
        },
        Odwolujacy: {
          krs: s(odw.krs),
          nazwa: s(odw.nazwa),
          nip: s(odw.nip),
          regon: s(odw.regon),
          przez_pelnomocnika: s(odw['przez-pelnomocnika'] ?? '1'),
          pelnomocnik_imie_nazwisko: s(pel.imie_nazwisko),
          pelnomocnik_nazwa: s(pel.nazwa),
          pelnomocnik_mail: s(pel.mail),
        },
        Zamawiajacy: {
          krs: s(zam.krs),
          nazwa: s(zam.nazwa),
          nip: s(zam.nip),
          regon: s(zam.regon),
          prowadzacy_postepowanie: s(zam.prowadzacy_postepowanie ?? 'null'),
        },
        ZamowieniePubliczne: {
          numer_bzp: s(zp.numer_bzp),
          numer_postepowania: s(zp.numer_postepowania),
          numer_ted: s(zp.numer_ted),
          tytul: s(zp.tytul),
        },
      };
    }

    if (doc.doc_class === 'pelnomocnictwo') {
      const m = (c.mocodawca || [])[0] || {};
      const data = m.data || {};
      const pod = (m.podpisujacy || [])[0] || {};
      const pel = (c.pelnomocnicy || [])[0] || {};
      pelnomocnictwo = {
        mocodawca: {
          typ: data.typ === 'osoba_fizyczna' ? 'osoba_fizyczna' : 'osoba_prawna',
          nazwa: s(data.nazwa),
          nip: s(data.nip),
          krs: s(data.krs),
          imie_nazwisko: s(data.imie_nazwisko),
          podpisujacy_imie_nazwisko: s(pod.imie_nazwisko),
        },
        pelnomocnicy: {
          imie_nazwisko: s(pel.imie_nazwisko),
          pesel: s(pel.pesel),
        },
      };
    }

    if (doc.doc_class === 'przelew') {
      const p = c.przelew_bankowy || {};
      przelew = {
        przelew_bankowy: {
          data_operacji: s(p.data_operacji),
          kwota: s(p.kwota),
          na_rachunek: s(p.na_rachunek),
          numer_transakcji: s(p.numer_transakcji),
          tytul: s(p.tytul),
          z_rachunku: s(p.z_rachunku),
        },
      };
    }
  }

  return { odwolanie, pelnomocnictwo, przelew };
}
