import { useState, useRef } from 'react';
import { extractZipFiles, type ExtractedFile } from './utils/zip';
import { ingestDocument, listDocuments, getClientToken } from './api';
import { hydrateForms } from './hydrate';

interface OdwolanieKioFields {
  data: string;
  czynnosc_dzien: string;
  czynnosc_powod_id: string;
  czynnosc_opis: string;
  miejscowosc: string;
}

interface OdwolujacyFields {
  krs: string;
  nazwa: string;
  nip: string;
  regon: string;
  przez_pelnomocnika: string; // "1" lub "0"
  pelnomocnik_imie_nazwisko: string;
  pelnomocnik_nazwa: string;
  pelnomocnik_mail: string;
}

interface ZamawiajacyFields {
  krs: string;
  nazwa: string;
  nip: string;
  regon: string;
  prowadzacy_postepowanie: string; // "null" | "1" | "0"
}

interface ZamowieniePubliczneFields {
  numer_bzp: string;
  numer_postepowania: string;
  numer_ted: string;
  tytul: string;
}

interface OdwolanieFormData {
  OdwolanieKIO: OdwolanieKioFields;
  Odwolujacy: OdwolujacyFields;
  Zamawiajacy: ZamawiajacyFields;
  ZamowieniePubliczne: ZamowieniePubliczneFields;
}

interface PelnomocnictwoMocodawcaFields {
  imie_nazwisko: string;
  krs: string;
  nazwa: string;
  nip: string;
  typ: 'osoba_prawna' | 'osoba_fizyczna';
  podpisujacy_imie_nazwisko: string;
}

interface PelnomocnikFields {
  imie_nazwisko: string;
  pesel: string;
}

interface PelnomocnictwoFormData {
  mocodawca: PelnomocnictwoMocodawcaFields;
  pelnomocnicy: PelnomocnikFields;
}

interface PrzelewBankowyFields {
  data_operacji: string;
  kwota: string;
  na_rachunek: string;
  numer_transakcji: string;
  tytul: string;
  z_rachunku: string;
}

interface PrzelewFormData {
  przelew_bankowy: PrzelewBankowyFields;
}

interface DocumentSlot {
  id: 'odwolanie' | 'pelnomocnictwo' | 'przelew';
  title: string;
  categoryLabel: string;
  defaultFilename: string;
  file?: ExtractedFile;
}

const CZYNNOSC_POWODY = [
  { id: '', label: '-wybierz-' },
  { id: '1', label: '1 - Decyzja o odrzuceniu oferty' },
  { id: '2', label: '2 - Ogłoszenie wyboru oferty' },
  { id: '3', label: '3 - Decyzja o wykluczeniu wykonawcy' },
  { id: '4', label: '4 - Publikacja specyfikacji warunków zamówienia (SWZ)' },
  { id: '5', label: '5 - Modyfikacja treści SWZ' },
  { id: '6', label: '6 - Odpowiedzi i wyjaśnienia do SWZ' },
  { id: '7', label: '7 - Zaniechanie odrzucenia oferty' },
  { id: '8', label: '8 - Zaniechanie wykluczenia wykonawcy' },
  { id: '9', label: '9 - Decyzja o unieważnieniu postępowania' },
  { id: '10', label: '10 - Zaniechanie unieważnienia postępowania' },
  { id: '11', label: '11 - Opis przedmiotu zamówienia (OPZ)' },
];

export default function App() {
  const [stage, setStage] = useState<'upload' | 'loading' | 'splitscreen'>('upload');
  const [selectedZip, setSelectedZip] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const [loadingProgress, setLoadingProgress] = useState(0);
  const [loadingStep, setLoadingStep] = useState(1);

  const [currentDocIndex, setCurrentDocIndex] = useState(0);
  const [docSlots, setDocSlots] = useState<DocumentSlot[]>([
    {
      id: 'odwolanie',
      title: '1. Odwołanie do KIO',
      categoryLabel: 'Odwołanie',
      defaultFilename: 'odwolanie.pdf',
    },
    {
      id: 'pelnomocnictwo',
      title: '2. Pełnomocnictwo',
      categoryLabel: 'Pełnomocnictwo',
      defaultFilename: 'pelnomocnictwo.pdf',
    },
    {
      id: 'przelew',
      title: '3. Potwierdzenie przelewu',
      categoryLabel: 'Przelew',
      defaultFilename: 'przelew.pdf',
    },
  ]);

  // Formularze – domyślnie puste, gotowe do wpisywania i poprawy
  const [odwolanieData, setOdwolanieData] = useState<OdwolanieFormData>({
    OdwolanieKIO: {
      data: '',
      czynnosc_dzien: '',
      czynnosc_powod_id: '',
      czynnosc_opis: '',
      miejscowosc: '',
    },
    Odwolujacy: {
      krs: '',
      nazwa: '',
      nip: '',
      regon: '',
      przez_pelnomocnika: '1',
      pelnomocnik_imie_nazwisko: '',
      pelnomocnik_nazwa: '',
      pelnomocnik_mail: '',
    },
    Zamawiajacy: {
      krs: '',
      nazwa: '',
      nip: '',
      regon: '',
      prowadzacy_postepowanie: 'null',
    },
    ZamowieniePubliczne: {
      numer_bzp: '',
      numer_postepowania: '',
      numer_ted: '',
      tytul: '',
    },
  });

  const [pelnomocnictwoData, setPelnomocnictwoData] = useState<PelnomocnictwoFormData>({
    mocodawca: {
      imie_nazwisko: '',
      krs: '',
      nazwa: '',
      nip: '',
      typ: 'osoba_prawna',
      podpisujacy_imie_nazwisko: '',
    },
    pelnomocnicy: {
      imie_nazwisko: '',
      pesel: '',
    },
  });

  const [przelewData, setPrzelewData] = useState<PrzelewFormData>({
    przelew_bankowy: {
      data_operacji: '',
      kwota: '',
      na_rachunek: '60 1010 1010 0081 3622 3100 0000',
      numer_transakcji: '',
      tytul: '',
      z_rachunku: '',
    },
  });

  const [saveNotification, setSaveNotification] = useState<string | null>(null);
  const [showJsonModal, setShowJsonModal] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [highContrast, setHighContrast] = useState(false);

  const toggleContrast = () => {
    const next = !highContrast;
    setHighContrast(next);
    if (next) {
      document.body.classList.add('high-contrast');
    } else {
      document.body.classList.remove('high-contrast');
    }
  };

  const setFontSize = (scale: number) => {
    document.documentElement.style.setProperty('--base-font-size', `${scale}px`);
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 2) + ' ' + units[i];
  };

  // Wypełnienie przykładowymi danymi ze screenshotów z oczekiwane-json
  const fillSampleGoldData = () => {
    if (currentDocIndex === 0) {
      setOdwolanieData({
        OdwolanieKIO: {
          data: '13.10.2025',
          czynnosc_dzien: '01.10.2025',
          czynnosc_powod_id: '4',
          czynnosc_opis: 'Publikacja specyfikacji warunków zamówienia (SWZ)',
          miejscowosc: 'Pruszków',
        },
        Odwolujacy: {
          krs: '0000054580',
          nazwa: 'STRABAG Sp. z o.o.',
          nip: '',
          regon: '',
          przez_pelnomocnika: '1',
          pelnomocnik_imie_nazwisko: 'Marcel Kielce',
          pelnomocnik_nazwa: 'Kancelaria Radców Prawnych',
          pelnomocnik_mail: 'info@prawnik.sy',
        },
        Zamawiajacy: {
          krs: '',
          nazwa: 'Filharmonia Pomorska im. Ignacego Jana Paderewskiego',
          nip: '5540240549',
          regon: '000279077',
          prowadzacy_postepowanie: 'null',
        },
        ZamowieniePubliczne: {
          numer_bzp: '',
          numer_postepowania: '',
          numer_ted: '641651-2025',
          tytul: 'Wykonanie robót budowlanych oraz dostawa i montaż wyposażenia w ramach zadania, polegającego na przebudowie i rozbudowie Filharmonii Pomorskiej w Bydgoszczy',
        },
      });
    } else if (currentDocIndex === 1) {
      setPelnomocnictwoData({
        mocodawca: {
          typ: 'osoba_prawna',
          nazwa: 'FAMBUD',
          nip: '8361772283',
          krs: '0000244633',
          imie_nazwisko: '',
          podpisujacy_imie_nazwisko: 'Paweł Podolski',
        },
        pelnomocnicy: {
          imie_nazwisko: 'Krystyna Mazowiecka',
          pesel: '85120133547',
        },
      });
    } else {
      setPrzelewData({
        przelew_bankowy: {
          data_operacji: '09.10.2025',
          kwota: '10000.00',
          na_rachunek: '60 1010 1010 0081 3622 3100 0000',
          numer_transakcji: '',
          tytul: 'WPIS OD ODW., ZAM: ZESPÓŁ SZKÓŁ CENTRUM KSZTAŁCENIA ROLNICZEGO IM. KEN W HENRYKOWIE, ZSCKR/822/2025, BUDOWA DR. POŻAR.',
          z_rachunku: '50 8020 5460 0000 5888 7442 44',
        },
      });
    }
    setSaveNotification(`Wstawiono dane dla: ${docSlots[currentDocIndex].title}`);
    setTimeout(() => setSaveNotification(null), 3000);
  };

  const clearCurrentData = () => {
    if (currentDocIndex === 0) {
      setOdwolanieData({
        OdwolanieKIO: { data: '', czynnosc_dzien: '', czynnosc_powod_id: '', czynnosc_opis: '', miejscowosc: '' },
        Odwolujacy: { krs: '', nazwa: '', nip: '', regon: '', przez_pelnomocnika: '1', pelnomocnik_imie_nazwisko: '', pelnomocnik_nazwa: '', pelnomocnik_mail: '' },
        Zamawiajacy: { krs: '', nazwa: '', nip: '', regon: '', prowadzacy_postepowanie: 'null' },
        ZamowieniePubliczne: { numer_bzp: '', numer_postepowania: '', numer_ted: '', tytul: '' },
      });
    } else if (currentDocIndex === 1) {
      setPelnomocnictwoData({
        mocodawca: { typ: 'osoba_prawna', nazwa: '', nip: '', krs: '', imie_nazwisko: '', podpisujacy_imie_nazwisko: '' },
        pelnomocnicy: { imie_nazwisko: '', pesel: '' },
      });
    } else {
      setPrzelewData({
        przelew_bankowy: { data_operacji: '', kwota: '', na_rachunek: '60 1010 1010 0081 3622 3100 0000', numer_transakcji: '', tytul: '', z_rachunku: '' },
      });
    }
  };

  // Pobranie wyników z bazy danych backendu (jeśli backend jest uruchomiony).
  const loadFromBackend = async () => {
    try {
      const docs = await listDocuments();
      if (docs.length === 0) {
        setSaveNotification('W bazie nie ma jeszcze żadnych wyników.');
      } else {
        const forms = hydrateForms(docs);
        if (forms.odwolanie) setOdwolanieData(forms.odwolanie);
        if (forms.pelnomocnictwo) setPelnomocnictwoData(forms.pelnomocnictwo);
        if (forms.przelew) setPrzelewData(forms.przelew);
        setSaveNotification(`Wczytano ${docs.length} dokument(ów) z bazy danych.`);
      }
    } catch {
      setSaveNotification('Nie udało się połączyć z bazą danych (backend może być wyłączony).');
    }
    setTimeout(() => setSaveNotification(null), 4000);
  };

  const handleFileSelection = (file: File) => {
    const isZip =
      file.name.toLowerCase().endsWith('.zip') ||
      file.type === 'application/zip' ||
      file.type === 'application/x-zip-compressed';

    if (!isZip) {
      setErrorMessage(`Wybrany plik („${file.name}”) nie jest archiwum .zip. Wybierz plik z rozszerzeniem .zip.`);
      setSelectedZip(null);
      return;
    }

    setErrorMessage(null);
    setSelectedZip(file);
  };

  const startProcessing = async () => {
    if (!selectedZip) return;

    setStage('loading');
    setLoadingProgress(10);
    setLoadingStep(1);

    let extracted: ExtractedFile[] = [];
    try {
      extracted = await extractZipFiles(selectedZip);
    } catch (e) {
      console.warn('Błąd odczytu ZIP:', e);
    }

    const newSlots = [...docSlots];
    if (extracted.length > 0) {
      const pdfs = extracted.filter((f) => f.name.toLowerCase().endsWith('.pdf'));
      const odw = pdfs.find((f) => f.name.toLowerCase().includes('odwol') || f.name.toLowerCase().includes('appeal'));
      const pel = pdfs.find((f) => f.name.toLowerCase().includes('pelnom') || f.name.toLowerCase().includes('power'));
      const prz = pdfs.find((f) => f.name.toLowerCase().includes('przel') || f.name.toLowerCase().includes('trans'));

      newSlots[0].file = odw || pdfs[0];
      newSlots[1].file = pel || pdfs[1];
      newSlots[2].file = prz || pdfs[2];
      setDocSlots(newSlots);
    }

    setTimeout(() => {
      setLoadingProgress(40);
      setLoadingStep(2);
    }, 500);

    setTimeout(() => {
      setLoadingProgress(75);
      setLoadingStep(3);
    }, 1000);

    setTimeout(() => {
      setLoadingProgress(100);
      setLoadingStep(4);
    }, 1500);

    setTimeout(() => {
      setStage('splitscreen');
    }, 1800);
  };

  const goToNextDoc = () => {
    if (currentDocIndex < docSlots.length - 1) {
      setCurrentDocIndex((prev) => prev + 1);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const goToPrevDoc = () => {
    if (currentDocIndex > 0) {
      setCurrentDocIndex((prev) => prev - 1);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const handleSaveData = async () => {
    try {
      const result = await ingestDocument({
        client_token: getClientToken(),
        doc_class: activeDoc.id,
        canonical_json: getCanonicalJson(),
        source_name: activeDoc.file?.name ?? activeDoc.defaultFilename,
      });
      setSaveNotification(
        result.correction_session_id
          ? 'Zapisano poprawkę — trafiła do bazy jako dane do douczania modelu.'
          : 'Zapisano wynik w bazie danych.'
      );
    } catch {
      setSaveNotification('Backend niedostępny — zmiany zostały w formularzu (demo działa dalej).');
    }
    setTimeout(() => setSaveNotification(null), 4000);
  };

  // Generowanie kanonicznego JSON zgodnego 1:1 z oczekiwane-json
  const getCanonicalJson = (index: number = currentDocIndex) => {
    if (index === 0) {
      const { OdwolanieKIO, Odwolujacy, Zamawiajacy, ZamowieniePubliczne } = odwolanieData;
      return {
        OdwolanieKIO: {
          data: OdwolanieKIO.data || null,
          czynnosc_dzien: OdwolanieKIO.czynnosc_dzien || null,
          czynnosc_powod_id: OdwolanieKIO.czynnosc_powod_id ? parseInt(OdwolanieKIO.czynnosc_powod_id) : null,
          czynnosc_opis: OdwolanieKIO.czynnosc_opis || null,
          miejscowosc: OdwolanieKIO.miejscowosc || null,
        },
        Odwolujacy: [
          {
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
          },
        ],
        Zamawiajacy: [
          {
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
          },
        ],
        ZamowieniePubliczne: {
          numer_bzp: ZamowieniePubliczne.numer_bzp || null,
          numer_postepowania: ZamowieniePubliczne.numer_postepowania || null,
          numer_ted: ZamowieniePubliczne.numer_ted || null,
          tytul: ZamowieniePubliczne.tytul || null,
        },
      };
    } else if (index === 1) {
      const { mocodawca, pelnomocnicy } = pelnomocnictwoData;
      return {
        mocodawca: [
          {
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
          },
        ],
        pelnomocnicy: [
          {
            imie_nazwisko: pelnomocnicy.imie_nazwisko || null,
            pesel: pelnomocnicy.pesel ? (isNaN(Number(pelnomocnicy.pesel)) ? pelnomocnicy.pesel : Number(pelnomocnicy.pesel)) : null,
          },
        ],
      };
    } else {
      const { przelew_bankowy } = przelewData;
      return {
        przelew_bankowy: {
          data_operacji: przelew_bankowy.data_operacji || null,
          kwota: przelew_bankowy.kwota ? parseFloat(przelew_bankowy.kwota.replace(',', '.')) : null,
          na_rachunek: przelew_bankowy.na_rachunek.replace(/\s+/g, '') || null,
          numer_transakcji: przelew_bankowy.numer_transakcji || null,
          tytul: przelew_bankowy.tytul || null,
          z_rachunku: przelew_bankowy.z_rachunku.replace(/\s+/g, '') || null,
        },
      };
    }
  };

  const activeDoc = docSlots[currentDocIndex];

  // Zapisuje wszystkie trzy dokumenty jednym kliknięciem.
  const saveAll = async () => {
    const token = getClientToken();
    let created = 0;
    let corrected = 0;
    try {
      for (let i = 0; i < docSlots.length; i++) {
        const slot = docSlots[i];
        const result = await ingestDocument({
          client_token: token,
          doc_class: slot.id,
          canonical_json: getCanonicalJson(i),
          source_name: slot.file?.name ?? slot.defaultFilename,
        });
        if (result.correction_session_id) corrected++;
        else created++;
      }
      setSaveNotification(
        `Zapisano wszystkie ${docSlots.length} dokumenty (nowe: ${created}, poprawki: ${corrected}).`
      );
    } catch {
      setSaveNotification('Backend niedostępny — zmiany zostały w formularzu (demo działa dalej).');
    }
    setTimeout(() => setSaveNotification(null), 4000);
  };

  return (
    <>
      {/* 1. TOPBAR GOV.PL */}
      <header className="gov-topbar">
        <div className="gov-container">
          <div className="gov-topbar-inner">
            <div className="gov-portal-brand">
              <span className="gov-portal-mark">gov.pl</span>
              <span className="gov-portal-subtitle">Serwis Rzeczypospolitej Polskiej</span>
            </div>
            <div className="gov-a11y-tools" role="group" aria-label="Narzędzia dostępności">
              <button
                type="button"
                className="a11y-btn"
                onClick={() => setFontSize(16)}
                aria-label="Domyślny rozmiar tekstu"
              >
                A
              </button>
              <button
                type="button"
                className="a11y-btn"
                onClick={() => setFontSize(18)}
                aria-label="Średni rozmiar tekstu"
              >
                A+
              </button>
              <button
                type="button"
                className="a11y-btn"
                onClick={() => setFontSize(20)}
                aria-label="Duży rozmiar tekstu"
              >
                A++
              </button>
              <button
                type="button"
                className="a11y-btn contrast-toggle"
                onClick={toggleContrast}
                aria-pressed={highContrast}
              >
                Kontrast
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* 2. GŁÓWNA ZAWARTOŚĆ */}
      <main className="gov-main">
        {/* ======================================================== */}
        {/* WIDOK 1: EKRAN WCZYTYWANIA ARCHIWUM .ZIP                 */}
        {/* ======================================================== */}
        {stage === 'upload' && (
          <div className="gov-container">
            <div className="service-header">
              <h1 className="service-title">Odwołania2json</h1>
            </div>

            <p className="service-description">
              Prześlij dokumentację sprawy odwoławczej w formacie .zip. System automatycznie rozpozna rodzaj każdego
              pisma, wyodrębni kluczowe informacje procesowe i umożliwi ich prostą weryfikację.
            </p>

            <section className="upload-section" aria-label="Przesyłanie dokumentacji">
              <input
                type="file"
                ref={fileInputRef}
                className="file-input-hidden"
                accept=".zip,application/zip,application/x-zip-compressed"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    handleFileSelection(e.target.files[0]);
                  }
                }}
              />

              <button
                type="button"
                className="gov-btn-primary"
                onClick={() => fileInputRef.current?.click()}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <span>Załaduj plik .zip</span>
              </button>

              <div
                className={`dropzone ${dragOver ? 'dragover' : ''}`}
                role="button"
                tabIndex={0}
                aria-label="Upuść plik .zip tutaj lub naciśnij Enter, aby wybrać z dysku"
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                    handleFileSelection(e.dataTransfer.files[0]);
                  }
                }}
              >
                <svg
                  className="dropzone-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                  <line x1="12" y1="11" x2="12" y2="17" />
                  <polyline points="9 14 12 11 15 14" />
                </svg>
                <p className="dropzone-label">lub upuść pliki tutaj</p>
                <p className="dropzone-hint">Akceptowany format: archiwum .zip (3 pisma w sprawie)</p>
              </div>

              {errorMessage && (
                <div className="status-box visible is-error" role="status" aria-live="polite">
                  <p className="status-title">Nieprawidłowy format pliku</p>
                  <p className="status-meta">{errorMessage}</p>
                </div>
              )}

              {selectedZip && !errorMessage && (
                <div className="status-box visible is-success" role="status" aria-live="polite">
                  <p className="status-title">Wybrano plik: {selectedZip.name}</p>
                  <p className="status-meta">
                    Rozmiar archiwum: {formatFileSize(selectedZip.size)} • Gotowy do analizy (3 dokumenty sprawy)
                  </p>
                  <div className="status-actions">
                    <button type="button" className="gov-btn-process" onClick={startProcessing}>
                      <span>Przetwórz do JSON</span>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width="18" height="18">
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={() => {
                        setSelectedZip(null);
                        if (fileInputRef.current) fileInputRef.current.value = '';
                      }}
                    >
                      Usuń plik
                    </button>
                  </div>
                </div>
              )}
            </section>

            <div className="gov-info-note">
              <strong>Informacja o przetwarzaniu:</strong> Archiwum powinno zawierać dokumenty sprawy odwoławczej (odwołanie, pełnomocnictwo oraz potwierdzenie uiszczenia wpisu).
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* WIDOK 2: EKRAN ŁADOWANIA (LOADING SCREEN)                */}
        {/* ======================================================== */}
        {stage === 'loading' && (
          <div className="gov-container">
            <div className="service-header">
              <h1 className="service-title">Przetwarzanie dokumentacji sprawy</h1>
            </div>

            <div className="gov-loading-card" role="status" aria-live="polite">
              <div style={{ display: 'flex', alignItems: 'center', gap: '20px', marginBottom: '16px' }}>
                <div className="gov-spinner" aria-hidden="true"></div>
                <div>
                  <h2 style={{ margin: '0 0 4px', fontSize: '1.25rem', fontWeight: 900, color: 'var(--gov-text)' }}>
                    Trwa analiza archiwum {selectedZip?.name}
                  </h2>
                  <p style={{ margin: 0, fontSize: '0.9375rem', color: 'var(--gov-text-muted)' }}>
                    Proszę czekać, system przygotowuje dane...
                  </p>
                </div>
              </div>

              <div className="gov-progress-bar-track" aria-hidden="true">
                <div className="gov-progress-bar-fill" style={{ width: `${loadingProgress}%` }}></div>
              </div>

              <div style={{ marginTop: '20px' }}>
                <div className={`gov-step-item ${loadingStep > 1 ? 'done' : loadingStep === 1 ? 'active' : ''}`}>
                  <span>{loadingStep > 1 ? '✓' : '•'}</span>
                  <span>1. Rozpakowywanie archiwum .zip (3 dokumenty procesowe)</span>
                </div>
                <div className={`gov-step-item ${loadingStep > 2 ? 'done' : loadingStep === 2 ? 'active' : ''}`}>
                  <span>{loadingStep > 2 ? '✓' : '•'}</span>
                  <span>2. Wykrywanie warstwy tekstowej i odczyt OCR Tesseract 5 pol</span>
                </div>
                <div className={`gov-step-item ${loadingStep > 3 ? 'done' : loadingStep === 3 ? 'active' : ''}`}>
                  <span>{loadingStep > 3 ? '✓' : '•'}</span>
                  <span>3. Walidacja sum kontrolnych (NIP, REGON, NRB)</span>
                </div>
                <div className={`gov-step-item ${loadingStep === 4 ? 'done' : ''}`}>
                  <span>{loadingStep === 4 ? '✓' : '•'}</span>
                  <span>4. Przygotowanie danych do panelu weryfikacji</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* WIDOK 3: SPLIT-SCREEN (CZYSTY, ESTETYCZNY DLA LUDZI)     */}
        {/* ======================================================== */}
        {stage === 'splitscreen' && (
          <div className="gov-container-wide">
            {/* Pasek nawigacyjny i przełącznik 3 plików */}
            <div className="gov-doc-nav-bar">
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 900, fontSize: '0.9375rem', color: 'var(--gov-text)' }}>
                  Pismo:
                </span>
                <div className="gov-tabs-list" role="tablist">
                  {docSlots.map((slot, index) => (
                    <button
                      key={slot.id}
                      type="button"
                      role="tab"
                      aria-selected={index === currentDocIndex}
                      className={`gov-tab-btn ${index === currentDocIndex ? 'active' : ''}`}
                      onClick={() => setCurrentDocIndex(index)}
                    >
                      {slot.title}
                    </button>
                  ))}
                </div>
              </div>

              {/* Przyciski nawigacji: Poprzedni / Następny plik */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <button
                  type="button"
                  className="gov-btn-secondary"
                  onClick={goToPrevDoc}
                  disabled={currentDocIndex === 0}
                  style={{ opacity: currentDocIndex === 0 ? 0.4 : 1, cursor: currentDocIndex === 0 ? 'not-allowed' : 'pointer' }}
                >
                  ← Poprzedni
                </button>

                <button
                  type="button"
                  className="gov-btn-process"
                  onClick={goToNextDoc}
                  disabled={currentDocIndex === docSlots.length - 1}
                  style={{ opacity: currentDocIndex === docSlots.length - 1 ? 0.5 : 1, cursor: currentDocIndex === docSlots.length - 1 ? 'not-allowed' : 'pointer' }}
                >
                  <span>Następny plik →</span>
                </button>

                <button
                  type="button"
                  className="gov-btn-secondary"
                  onClick={() => {
                    setStage('upload');
                    setSelectedZip(null);
                  }}
                  title="Załaduj inny plik .zip"
                >
                  Nowy .zip
                </button>
              </div>
            </div>

            {/* Powiadomienie o zapisaniu */}
            {saveNotification && (
              <div
                style={{
                  marginTop: '10px',
                  padding: '10px 16px',
                  backgroundColor: 'var(--gov-success-bg)',
                  borderLeft: '4px solid var(--gov-success)',
                  color: 'var(--gov-success)',
                  fontWeight: 700,
                  fontSize: '0.875rem',
                  borderRadius: '0 3px 3px 0',
                }}
              >
                ✓ {saveNotification}
              </div>
            )}

            {/* UKŁAD DZIELONY: SPLIT-SCREEN (50% / 50%) */}
            <div className="gov-split-layout">
              {/* --- LEWA STRONA: PODGLĄD PDF --- */}
              <div className="gov-split-pane">
                <div className="gov-pane-header">
                  <h2 className="gov-pane-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                      <line x1="16" y1="13" x2="8" y2="13"></line>
                      <line x1="16" y1="17" x2="8" y2="17"></line>
                    </svg>
                    <span>
                      Podgląd: {activeDoc.file?.name || activeDoc.defaultFilename}
                    </span>
                  </h2>
                  <span className="gov-badge">Dokument {currentDocIndex + 1} z 3</span>
                </div>

                <div className="gov-pdf-frame-wrapper">
                  {activeDoc.file ? (
                    <iframe
                      src={activeDoc.file.url}
                      className="gov-pdf-frame"
                      title={`Podgląd PDF ${activeDoc.title}`}
                    />
                  ) : (
                    <div
                      style={{
                        height: '100%',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#dfe2e6',
                        textAlign: 'center',
                        padding: '24px',
                      }}
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="54" height="54" style={{ marginBottom: '14px', opacity: 0.8 }}>
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                      </svg>
                      <h3 style={{ margin: '0 0 6px', fontSize: '1.125rem', color: '#ffffff' }}>
                        {activeDoc.title}
                      </h3>
                      <p style={{ margin: '0 0 14px', maxWidth: '340px', fontSize: '0.875rem', color: '#8c939d' }}>
                        W tym oknie wyświetla się plik <strong>{activeDoc.defaultFilename}</strong> z wgranego archiwum .zip.
                      </p>
                      <span className="gov-badge warning">Podgląd dokumentu</span>
                    </div>
                  )}
                </div>
              </div>

              {/* --- PRAWA STRONA: CZYSTE, PROSTE POLA BEZ PRZYTŁACZANIA (IMAGE 2 STYLE) --- */}
              <div className="gov-split-pane">
                <div className="gov-pane-header">
                  <div>
                    <h2 className="gov-pane-title">
                      {activeDoc.title}
                    </h2>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={fillSampleGoldData}
                      title="Wstaw przykładowe dane z wzorca"
                    >
                      Wstaw przykład
                    </button>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={clearCurrentData}
                      title="Wyczyść wszystkie pola"
                    >
                      Wyczyść
                    </button>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={loadFromBackend}
                      title="Pobierz wyniki z bazy danych backendu"
                    >
                      Wczytaj z bazy
                    </button>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={() => setShowJsonModal(true)}
                    >
                      Podgląd JSON
                    </button>
                  </div>
                </div>

                <div className="gov-form-wrapper">
                  {/* ======================================================== */}
                  {/* DOKUMENT 1: ODWOŁANIE DO KIO                             */}
                  {/* ======================================================== */}
                  {currentDocIndex === 0 && (
                    <div>
                      {/* Sekcja: OdwolanieKIO */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "OdwolanieKIO"
                          </h3>
                          <span className="gov-badge">Obiekt główny</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_data">Data:</label>
                          <input
                            id="odw_data"
                            type="text"
                            className="clean-input"
                            placeholder="dd.mm.rrrr"
                            value={odwolanieData.OdwolanieKIO.data}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                OdwolanieKIO: { ...odwolanieData.OdwolanieKIO, data: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_miejscowosc">Miejscowość:</label>
                          <input
                            id="odw_miejscowosc"
                            type="text"
                            className="clean-input"
                            placeholder="np. Warszawa"
                            value={odwolanieData.OdwolanieKIO.miejscowosc}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                OdwolanieKIO: { ...odwolanieData.OdwolanieKIO, miejscowosc: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_powod">Powód:</label>
                          <select
                            id="odw_powod"
                            className="clean-select"
                            value={odwolanieData.OdwolanieKIO.czynnosc_powod_id}
                            onChange={(e) => {
                              const sel = CZYNNOSC_POWODY.find((p) => p.id === e.target.value);
                              setOdwolanieData({
                                ...odwolanieData,
                                OdwolanieKIO: {
                                  ...odwolanieData.OdwolanieKIO,
                                  czynnosc_powod_id: e.target.value,
                                  czynnosc_opis: sel && sel.id ? sel.label.replace(/^\d+ - /, '') : '',
                                },
                              });
                            }}
                          >
                            {CZYNNOSC_POWODY.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.label}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_czynnosc_dzien">Data czynności:</label>
                          <input
                            id="odw_czynnosc_dzien"
                            type="text"
                            className="clean-input"
                            placeholder="dd.mm.rrrr"
                            value={odwolanieData.OdwolanieKIO.czynnosc_dzien}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                OdwolanieKIO: { ...odwolanieData.OdwolanieKIO, czynnosc_dzien: e.target.value },
                              })
                            }
                          />
                        </div>
                      </div>

                      {/* Sekcja: Odwolujacy */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "Odwolujacy"
                          </h3>
                          <span className="gov-badge">Podmiot wnoszący</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_nazwa">Nazwa:</label>
                          <input
                            id="odw_nazwa"
                            type="text"
                            className="clean-input"
                            placeholder="Pełna nazwa wykonawcy"
                            value={odwolanieData.Odwolujacy.nazwa}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, nazwa: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_nip">NIP:</label>
                          <input
                            id="odw_nip"
                            type="text"
                            className="clean-input"
                            placeholder="10 cyfr"
                            value={odwolanieData.Odwolujacy.nip}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, nip: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_krs">KRS:</label>
                          <input
                            id="odw_krs"
                            type="text"
                            className="clean-input"
                            placeholder="Numer KRS"
                            value={odwolanieData.Odwolujacy.krs}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, krs: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_regon">REGON:</label>
                          <input
                            id="odw_regon"
                            type="text"
                            className="clean-input"
                            placeholder="Numer REGON"
                            value={odwolanieData.Odwolujacy.regon}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, regon: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="odw_pelnomocnik_check">Przez pełnomocnika:</label>
                          <select
                            id="odw_pelnomocnik_check"
                            className="clean-select"
                            value={odwolanieData.Odwolujacy.przez_pelnomocnika}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, przez_pelnomocnika: e.target.value },
                              })
                            }
                          >
                            <option value="1">Tak (1)</option>
                            <option value="0">Nie (0)</option>
                          </select>
                        </div>

                        {odwolanieData.Odwolujacy.przez_pelnomocnika === '1' && (
                          <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px dashed var(--gov-border-light)' }}>
                            <div className="clean-row">
                              <label className="clean-label" htmlFor="odw_pel_imie">Pełnomocnik:</label>
                              <input
                                id="odw_pel_imie"
                                type="text"
                                className="clean-input"
                                placeholder="Imię i nazwisko"
                                value={odwolanieData.Odwolujacy.pelnomocnik_imie_nazwisko}
                                onChange={(e) =>
                                  setOdwolanieData({
                                    ...odwolanieData,
                                    Odwolujacy: { ...odwolanieData.Odwolujacy, pelnomocnik_imie_nazwisko: e.target.value },
                                  })
                                }
                              />
                            </div>

                            <div className="clean-row">
                              <label className="clean-label" htmlFor="odw_pel_nazwa">Kancelaria:</label>
                              <input
                                id="odw_pel_nazwa"
                                type="text"
                                className="clean-input"
                                placeholder="Nazwa kancelarii"
                                value={odwolanieData.Odwolujacy.pelnomocnik_nazwa}
                                onChange={(e) =>
                                  setOdwolanieData({
                                    ...odwolanieData,
                                    Odwolujacy: { ...odwolanieData.Odwolujacy, pelnomocnik_nazwa: e.target.value },
                                  })
                                }
                              />
                            </div>

                            <div className="clean-row">
                              <label className="clean-label" htmlFor="odw_pel_mail">E-mail:</label>
                              <input
                                id="odw_pel_mail"
                                type="email"
                                className="clean-input"
                                placeholder="Adres e-mail"
                                value={odwolanieData.Odwolujacy.pelnomocnik_mail}
                                onChange={(e) =>
                                  setOdwolanieData({
                                    ...odwolanieData,
                                    Odwolujacy: { ...odwolanieData.Odwolujacy, pelnomocnik_mail: e.target.value },
                                  })
                                }
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Sekcja: Zamawiajacy */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "Zamawiajacy"
                          </h3>
                          <span className="gov-badge">Instytucja zamawiająca</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_nazwa">Nazwa:</label>
                          <input
                            id="zam_nazwa"
                            type="text"
                            className="clean-input"
                            placeholder="Pełna nazwa zamawiającego"
                            value={odwolanieData.Zamawiajacy.nazwa}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, nazwa: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_nip">NIP:</label>
                          <input
                            id="zam_nip"
                            type="text"
                            className="clean-input"
                            placeholder="NIP zamawiającego"
                            value={odwolanieData.Zamawiajacy.nip}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, nip: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_regon">REGON:</label>
                          <input
                            id="zam_regon"
                            type="text"
                            className="clean-input"
                            placeholder="REGON"
                            value={odwolanieData.Zamawiajacy.regon}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, regon: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_krs">KRS:</label>
                          <input
                            id="zam_krs"
                            type="text"
                            className="clean-input"
                            placeholder="Numer KRS (jeśli dotyczy)"
                            value={odwolanieData.Zamawiajacy.krs}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, krs: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_prowadzacy">Lider postępowania:</label>
                          <select
                            id="zam_prowadzacy"
                            className="clean-select"
                            value={odwolanieData.Zamawiajacy.prowadzacy_postepowanie}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, prowadzacy_postepowanie: e.target.value },
                              })
                            }
                          >
                            <option value="null">Brak informacji / Pojedynczy</option>
                            <option value="1">Tak (1)</option>
                            <option value="0">Nie (0)</option>
                          </select>
                        </div>
                      </div>

                      {/* Sekcja: ZamowieniePubliczne */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "ZamowieniePubliczne"
                          </h3>
                          <span className="gov-badge">Postępowanie</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_tytul">Tytuł:</label>
                          <textarea
                            id="zam_tytul"
                            className="clean-textarea"
                            rows={2}
                            placeholder="Tytuł / przedmiot zamówienia"
                            value={odwolanieData.ZamowieniePubliczne.tytul}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                ZamowieniePubliczne: {
                                  ...odwolanieData.ZamowieniePubliczne,
                                  tytul: e.target.value,
                                },
                              })
                            }
                          ></textarea>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_nr_post">Nr postępowania:</label>
                          <input
                            id="zam_nr_post"
                            type="text"
                            className="clean-input"
                            placeholder="np. ZP.039.2025"
                            value={odwolanieData.ZamowieniePubliczne.numer_postepowania}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                ZamowieniePubliczne: {
                                  ...odwolanieData.ZamowieniePubliczne,
                                  numer_postepowania: e.target.value,
                                },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_bzp">Nr BZP:</label>
                          <input
                            id="zam_bzp"
                            type="text"
                            className="clean-input"
                            placeholder="np. 2025/BZP 00123456/01"
                            value={odwolanieData.ZamowieniePubliczne.numer_bzp}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                ZamowieniePubliczne: {
                                  ...odwolanieData.ZamowieniePubliczne,
                                  numer_bzp: e.target.value,
                                },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="zam_ted">Nr TED:</label>
                          <input
                            id="zam_ted"
                            type="text"
                            className="clean-input"
                            placeholder="np. 641651-2025"
                            value={odwolanieData.ZamowieniePubliczne.numer_ted}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                ZamowieniePubliczne: {
                                  ...odwolanieData.ZamowieniePubliczne,
                                  numer_ted: e.target.value,
                                },
                              })
                            }
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ======================================================== */}
                  {/* DOKUMENT 2: PEŁNOMOCNICTWO                               */}
                  {/* ======================================================== */}
                  {currentDocIndex === 1 && (
                    <div>
                      {/* Sekcja: Mocodawca */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "mocodawca"
                          </h3>
                          <span className="gov-badge">Udzielający</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="moc_typ">Typ:</label>
                          <select
                            id="moc_typ"
                            className="clean-select"
                            value={pelnomocnictwoData.mocodawca.typ}
                            onChange={(e) =>
                              setPelnomocnictwoData({
                                ...pelnomocnictwoData,
                                mocodawca: {
                                  ...pelnomocnictwoData.mocodawca,
                                  typ: e.target.value as 'osoba_prawna' | 'osoba_fizyczna',
                                },
                              })
                            }
                          >
                            <option value="osoba_prawna">Osoba prawna</option>
                            <option value="osoba_fizyczna">Osoba fizyczna</option>
                          </select>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="moc_nazwa">Nazwa:</label>
                          <input
                            id="moc_nazwa"
                            type="text"
                            className="clean-input"
                            placeholder={pelnomocnictwoData.mocodawca.typ === 'osoba_prawna' ? 'Pełna nazwa mocodawcy' : 'Imię i nazwisko'}
                            value={pelnomocnictwoData.mocodawca.typ === 'osoba_prawna' ? pelnomocnictwoData.mocodawca.nazwa : pelnomocnictwoData.mocodawca.imie_nazwisko}
                            onChange={(e) => {
                              if (pelnomocnictwoData.mocodawca.typ === 'osoba_prawna') {
                                setPelnomocnictwoData({
                                  ...pelnomocnictwoData,
                                  mocodawca: { ...pelnomocnictwoData.mocodawca, nazwa: e.target.value },
                                });
                              } else {
                                setPelnomocnictwoData({
                                  ...pelnomocnictwoData,
                                  mocodawca: { ...pelnomocnictwoData.mocodawca, imie_nazwisko: e.target.value },
                                });
                              }
                            }}
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="moc_nip">NIP:</label>
                          <input
                            id="moc_nip"
                            type="text"
                            className="clean-input"
                            placeholder="Numer NIP"
                            value={pelnomocnictwoData.mocodawca.nip}
                            onChange={(e) =>
                              setPelnomocnictwoData({
                                ...pelnomocnictwoData,
                                mocodawca: { ...pelnomocnictwoData.mocodawca, nip: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="moc_krs">KRS:</label>
                          <input
                            id="moc_krs"
                            type="text"
                            className="clean-input"
                            placeholder="Numer KRS"
                            value={pelnomocnictwoData.mocodawca.krs}
                            onChange={(e) =>
                              setPelnomocnictwoData({
                                ...pelnomocnictwoData,
                                mocodawca: { ...pelnomocnictwoData.mocodawca, krs: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="moc_podpis">Osoba podpisująca:</label>
                          <input
                            id="moc_podpis"
                            type="text"
                            className="clean-input"
                            placeholder="Imię i nazwisko osoby podpisującej"
                            value={pelnomocnictwoData.mocodawca.podpisujacy_imie_nazwisko}
                            onChange={(e) =>
                              setPelnomocnictwoData({
                                ...pelnomocnictwoData,
                                mocodawca: {
                                  ...pelnomocnictwoData.mocodawca,
                                  podpisujacy_imie_nazwisko: e.target.value,
                                },
                              })
                            }
                          />
                        </div>
                      </div>

                      {/* Sekcja: Pełnomocnicy */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "pelnomocnicy"
                          </h3>
                          <span className="gov-badge">Otrzymujący</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="pel_imie">Imię i nazwisko:</label>
                          <input
                            id="pel_imie"
                            type="text"
                            className="clean-input"
                            placeholder="w mianowniku"
                            value={pelnomocnictwoData.pelnomocnicy.imie_nazwisko}
                            onChange={(e) =>
                              setPelnomocnictwoData({
                                ...pelnomocnictwoData,
                                pelnomocnicy: { ...pelnomocnictwoData.pelnomocnicy, imie_nazwisko: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="pel_pesel">PESEL:</label>
                          <input
                            id="pel_pesel"
                            type="text"
                            className="clean-input"
                            placeholder="11 cyfr PESEL"
                            value={pelnomocnictwoData.pelnomocnicy.pesel}
                            onChange={(e) =>
                              setPelnomocnictwoData({
                                ...pelnomocnictwoData,
                                pelnomocnicy: { ...pelnomocnictwoData.pelnomocnicy, pesel: e.target.value },
                              })
                            }
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ======================================================== */}
                  {/* DOKUMENT 3: POTWIERDZENIE PRZELEWU                       */}
                  {/* ======================================================== */}
                  {currentDocIndex === 2 && (
                    <div>
                      {/* Sekcja: Przelew bankowy */}
                      <div className="clean-form-section">
                        <div className="clean-section-header">
                          <h3 className="clean-section-title">
                            Kategoria: "przelew_bankowy"
                          </h3>
                          <span className="gov-badge">Wpis KIO</span>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="prz_data">Data operacji:</label>
                          <input
                            id="prz_data"
                            type="text"
                            className="clean-input"
                            placeholder="dd.mm.rrrr"
                            value={przelewData.przelew_bankowy.data_operacji}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, data_operacji: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="prz_kwota">Kwota:</label>
                          <input
                            id="prz_kwota"
                            type="text"
                            className="clean-input"
                            placeholder="np. 10 000.00"
                            value={przelewData.przelew_bankowy.kwota}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, kwota: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="prz_na_rachunek">Na rachunek:</label>
                          <input
                            id="prz_na_rachunek"
                            type="text"
                            className="clean-input"
                            placeholder="60 1010 1010 0081 3622 3100 0000"
                            value={przelewData.przelew_bankowy.na_rachunek}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, na_rachunek: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="prz_z_rachunku">Z rachunku:</label>
                          <input
                            id="prz_z_rachunku"
                            type="text"
                            className="clean-input"
                            placeholder="26 cyfr nadawcy"
                            value={przelewData.przelew_bankowy.z_rachunku}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, z_rachunku: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="prz_tytul">Tytuł:</label>
                          <textarea
                            id="prz_tytul"
                            className="clean-textarea"
                            rows={2}
                            placeholder="Tytuł przelewu"
                            value={przelewData.przelew_bankowy.tytul}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, tytul: e.target.value },
                              })
                            }
                          ></textarea>
                        </div>

                        <div className="clean-row">
                          <label className="clean-label" htmlFor="prz_nr_transakcji">Nr transakcji:</label>
                          <input
                            id="prz_nr_transakcji"
                            type="text"
                            className="clean-input"
                            placeholder="opcjonalny numer transakcji"
                            value={przelewData.przelew_bankowy.numer_transakcji}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, numer_transakcji: e.target.value },
                              })
                            }
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Dolny pasek akcji formularza */}
                  <div style={{ marginTop: '20px', paddingTop: '14px', borderTop: '1px solid var(--gov-border-light)', display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                      <button type="button" className="gov-btn-process" onClick={handleSaveData}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" width="16" height="16">
                          <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                          <polyline points="17 21 17 13 7 13 7 21"></polyline>
                          <polyline points="7 3 7 8 15 8"></polyline>
                        </svg>
                        <span>Zapisz</span>
                      </button>
                      <button
                        type="button"
                        className="gov-btn-secondary"
                        onClick={saveAll}
                        title="Zapisz odwołanie, pełnomocnictwo i przelew jednym kliknięciem"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" width="16" height="16">
                          <polyline points="1 13 6 18 15 7"></polyline>
                          <polyline points="9 13 14 18 23 7"></polyline>
                        </svg>
                        <span>Zapisz wszystko</span>
                      </button>
                    </div>

                    {currentDocIndex < docSlots.length - 1 ? (
                      <button type="button" className="gov-btn-primary" onClick={goToNextDoc} style={{ maxWidth: '200px' }}>
                        <span>Następny plik →</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="gov-btn-primary"
                        onClick={() => setShowJsonModal(true)}
                        style={{ maxWidth: '240px' }}
                      >
                        <span>Pobierz JSON</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* 3. MODAL PODGLĄDU KANONICZNEGO JSON */}
      {showJsonModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
          role="dialog"
          aria-modal="true"
        >
          <div
            style={{
              backgroundColor: 'var(--gov-bg)',
              color: 'var(--gov-text)',
              border: '2px solid var(--gov-border)',
              borderRadius: '4px',
              maxWidth: '720px',
              width: '100%',
              maxHeight: '85vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div
              style={{
                padding: '14px 18px',
                borderBottom: '1px solid var(--gov-border-light)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <h3 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 900 }}>
                Kanoniczny JSON: {activeDoc.id}.json
              </h3>
              <button
                type="button"
                className="a11y-btn"
                onClick={() => setShowJsonModal(false)}
                style={{ fontSize: '0.875rem', padding: '3px 8px' }}
              >
                ✕
              </button>
            </div>

            <div style={{ padding: '16px', overflowY: 'auto', flex: 1, backgroundColor: 'var(--gov-surface)' }}>
              <pre
                style={{
                  margin: 0,
                  fontFamily: 'monospace',
                  fontSize: '0.8125rem',
                  lineHeight: '1.5',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {JSON.stringify(getCanonicalJson(), null, 2)}
              </pre>
            </div>

            <div
              style={{
                padding: '12px 18px',
                borderTop: '1px solid var(--gov-border-light)',
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '10px',
              }}
            >
              <button
                type="button"
                className="gov-btn-secondary"
                onClick={() => {
                  const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(getCanonicalJson(), null, 2));
                  const dlAnchorElem = document.createElement('a');
                  dlAnchorElem.setAttribute('href', dataStr);
                  dlAnchorElem.setAttribute('download', `${activeDoc.id}.json`);
                  dlAnchorElem.click();
                }}
              >
                Pobierz .json
              </button>
              <button
                type="button"
                className="gov-btn-process"
                onClick={() => setShowJsonModal(false)}
              >
                Zamknij
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 4. FOOTER GOV.PL */}
      <footer className="gov-footer">
        <div className="gov-container">
          <div className="gov-footer-inner">
            <span>Odwołania2json &bull; Moduł konwersji dokumentacji procesowej UZP</span>
            <span>Zgodność ze standardem WCAG 2.1</span>
          </div>
        </div>
      </footer>
    </>
  );
}
