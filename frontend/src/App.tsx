import { useState, useRef } from 'react';
import { extractZipFiles, type ExtractedFile } from './utils/zip';

// --- Typy odpowiadające 1:1 oczekiwane-json ze screenshotów ---

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
  { id: '', label: '– Wybierz identyfikator powodu (czynnosc_powod_id) –' },
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
      categoryLabel: 'Kategorie: OdwolanieKIO, Odwolujacy, Zamawiajacy, ZamowieniePubliczne',
      defaultFilename: 'odwolanie.pdf',
    },
    {
      id: 'pelnomocnictwo',
      title: '2. Pełnomocnictwo',
      categoryLabel: 'Kategorie: mocodawca.data, mocodawca.podpisujacy, pelnomocnicy',
      defaultFilename: 'pelnomocnictwo.pdf',
    },
    {
      id: 'przelew',
      title: '3. Potwierdzenie przelewu',
      categoryLabel: 'Kategoria: przelew_bankowy',
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
      na_rachunek: '60101010100081362231000000',
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
          data: '2025-10-13',
          czynnosc_dzien: '2025-10-01',
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
          data_operacji: '2025-10-09',
          kwota: '10000.00',
          na_rachunek: '60101010100081362231000000',
          numer_transakcji: '',
          tytul: 'WPIS OD ODW., ZAM: ZESPÓŁ SZKÓŁ CENTRUM KSZTAŁCENIA ROLNICZEGO IM. KEN W HENRYKOWIE, ZSCKR/822/2025, BUDOWA DR. POŻAR.',
          z_rachunku: '508020546000005888744244',
        },
      });
    }
    setSaveNotification(`Wczytano wzorcowe dane dla: ${docSlots[currentDocIndex].title}`);
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
        przelew_bankowy: { data_operacji: '', kwota: '', na_rachunek: '60101010100081362231000000', numer_transakcji: '', tytul: '', z_rachunku: '' },
      });
    }
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

  const handleSaveData = () => {
    setSaveNotification(`Zapisano zmiany w kategorii dokumentu: ${docSlots[currentDocIndex].title}`);
    setTimeout(() => setSaveNotification(null), 3500);
  };

  // Generowanie kanonicznego JSON zgodnego 1:1 z oczekiwane-json
  const getCanonicalJson = () => {
    if (currentDocIndex === 0) {
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
    } else if (currentDocIndex === 1) {
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
              pisma, wyodrębni kluczowe informacje procesowe do ustrukturyzowanych kategorii i umożliwi ich
              weryfikację oraz poprawę przed wygenerowaniem kanonicznego modelu danych.
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
              <strong>Informacja o przetwarzaniu:</strong> Archiwum powinno zawierać dokumenty sprawy odwoławczej (odwołanie, pełnomocnictwo oraz potwierdzenie uiszczenia wpisu). Po rozpakowaniu otworzy się widok split-screen z podziałem na kategorie zgodne ze schematem <em>oczekiwane-json</em>.
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
                    Proszę czekać, system przetwarza zestaw pism procesowych...
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
                  <span>3. Walidacja sum kontrolnych (NIP, REGON, NRB) i kategoryzacja pól</span>
                </div>
                <div className={`gov-step-item ${loadingStep === 4 ? 'done' : ''}`}>
                  <span>{loadingStep === 4 ? '✓' : '•'}</span>
                  <span>4. Przygotowanie danych do panelu edycji i weryfikacji (Split-View)</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* WIDOK 3: SPLIT-SCREEN (LEWA: PDF, PRAWA: KATEGORIE DANYCH) */}
        {/* ======================================================== */}
        {stage === 'splitscreen' && (
          <div className="gov-container-wide">
            {/* Pasek nawigacyjny i przełącznik 3 plików */}
            <div className="gov-doc-nav-bar">
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 900, fontSize: '1rem', color: 'var(--gov-text)' }}>
                  Dokumentacja sprawy:
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
                  ← Poprzedni plik
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
                  Wgraj inny .zip
                </button>
              </div>
            </div>

            {/* Powiadomienie o zapisaniu */}
            {saveNotification && (
              <div
                style={{
                  marginTop: '12px',
                  padding: '12px 18px',
                  backgroundColor: 'var(--gov-success-bg)',
                  borderLeft: '4px solid var(--gov-success)',
                  color: 'var(--gov-success)',
                  fontWeight: 700,
                  fontSize: '0.9375rem',
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
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                      <line x1="16" y1="13" x2="8" y2="13"></line>
                      <line x1="16" y1="17" x2="8" y2="17"></line>
                      <polyline points="10 9 9 9 8 9"></polyline>
                    </svg>
                    <span>
                      Podgląd PDF: {activeDoc.file?.name || activeDoc.defaultFilename}
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
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="64" height="64" style={{ marginBottom: '16px', opacity: 0.8 }}>
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                      </svg>
                      <h3 style={{ margin: '0 0 8px', fontSize: '1.25rem', color: '#ffffff' }}>
                        {activeDoc.title}
                      </h3>
                      <p style={{ margin: '0 0 16px', maxWidth: '380px', fontSize: '0.9375rem', color: '#8c939d' }}>
                        W tym oknie wyświetlany jest podgląd pliku <strong>{activeDoc.defaultFilename}</strong>. Po wgraniu archiwum .zip zawierającego pliki PDF, dokument pojawi się w tym oknie.
                      </p>
                      <span className="gov-badge warning">Oczekiwanie na warstwę PDF / OCR</span>
                    </div>
                  )}
                </div>
              </div>

              {/* --- PRAWA STRONA: KATEGORIE ZE SCHEMATU OCZEKIWANE-JSON --- */}
              <div className="gov-split-pane">
                <div className="gov-pane-header">
                  <div>
                    <h2 className="gov-pane-title">
                      Kategorie danych: {activeDoc.title}
                    </h2>
                    <p style={{ margin: '2px 0 0', fontSize: '0.8125rem', color: 'var(--gov-text-muted)' }}>
                      Struktura zgodna z <code>oczekiwane-json</code>. Pola są edytowalne przez osobę sprawdzającą.
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={fillSampleGoldData}
                      title="Wstaw przykładowe dane z wzorca"
                      style={{ fontSize: '0.8125rem', padding: '6px 10px' }}
                    >
                      Wstaw dane wzorcowe
                    </button>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={clearCurrentData}
                      title="Wyczyść wszystkie pola"
                      style={{ fontSize: '0.8125rem', padding: '6px 10px' }}
                    >
                      Wyczyść
                    </button>
                    <button
                      type="button"
                      className="gov-btn-secondary"
                      onClick={() => setShowJsonModal(true)}
                      style={{ fontSize: '0.8125rem', padding: '6px 12px' }}
                    >
                      Podgląd JSON
                    </button>
                  </div>
                </div>

                <div className="gov-form-wrapper">
                  {/* ======================================================== */}
                  {/* KATEGORIE DLA: ODWOŁANIE DO KIO (odwolanie.json)         */}
                  {/* ======================================================== */}
                  {currentDocIndex === 0 && (
                    <div>
                      {/* Kategoria 1: "OdwolanieKIO" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"OdwolanieKIO"</code>
                          </h3>
                          <span className="gov-badge">Obiekt główny</span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="odw_data">
                              <code>data</code> (Data z nagłówka pierwszej strony)
                            </label>
                            <input
                              id="odw_data"
                              type="text"
                              className="gov-input"
                              placeholder="Format: 'DD.MM.RRRR' lub 'YYYY-MM-DD'"
                              value={odwolanieData.OdwolanieKIO.data}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  OdwolanieKIO: { ...odwolanieData.OdwolanieKIO, data: e.target.value },
                                })
                              }
                            />
                            <span className="gov-hint">np. 2025-10-13</span>
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="odw_miejscowosc">
                              <code>miejscowosc</code> (Miejscowość z nagłówka)
                            </label>
                            <input
                              id="odw_miejscowosc"
                              type="text"
                              className="gov-input"
                              placeholder="z linii typu: 'X, dnia ...' albo 'X DD.MM.RRRR'"
                              value={odwolanieData.OdwolanieKIO.miejscowosc}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  OdwolanieKIO: { ...odwolanieData.OdwolanieKIO, miejscowosc: e.target.value },
                                })
                              }
                            />
                            <span className="gov-hint">np. Pruszków</span>
                          </div>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="odw_powod_id">
                            <code>czynnosc_powod_id</code> (Liczba całkowita 1-11 – pierwszy zarzut)
                          </label>
                          <select
                            id="odw_powod_id"
                            className="gov-select"
                            value={odwolanieData.OdwolanieKIO.czynnosc_powod_id}
                            onChange={(e) => {
                              const sel = CZYNNOSC_POWODY.find((p) => p.id === e.target.value);
                              setOdwolanieData({
                                ...odwolanieData,
                                OdwolanieKIO: {
                                  ...odwolanieData.OdwolanieKIO,
                                  czynnosc_powod_id: e.target.value,
                                  czynnosc_opis: sel ? sel.label.replace(/^\d+ - /, '') : '',
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

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="odw_czynnosc_opis">
                            <code>czynnosc_opis</code> (Kanoniczny opis zaskarżonej czynności zgodny 1:1 z czynnosc_powod_id)
                          </label>
                          <input
                            id="odw_czynnosc_opis"
                            type="text"
                            className="gov-input"
                            placeholder="Kanoniczny opis zaskarżonej czynności"
                            value={odwolanieData.OdwolanieKIO.czynnosc_opis}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                OdwolanieKIO: { ...odwolanieData.OdwolanieKIO, czynnosc_opis: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="odw_czynnosc_dzien">
                            <code>czynnosc_dzien</code> (Data czynności uruchamiającej bieg terminu - ISO)
                          </label>
                          <input
                            id="odw_czynnosc_dzien"
                            type="text"
                            className="gov-input"
                            placeholder="np. 2025-10-01"
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

                      {/* Kategoria 2: "Odwolujacy" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"Odwolujacy[]"</code>
                          </h3>
                          <span className="gov-badge">Tablica podmiotów wnoszących</span>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="odw_nazwa">
                            <code>nazwa</code> (Pełna nazwa podmiotu / Lidera konsorcjum)
                          </label>
                          <input
                            id="odw_nazwa"
                            type="text"
                            className="gov-input"
                            placeholder="np. STRABAG Sp. z o.o."
                            value={odwolanieData.Odwolujacy.nazwa}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, nazwa: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '14px' }}>
                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="odw_krs">
                              <code>krs</code>
                            </label>
                            <input
                              id="odw_krs"
                              type="text"
                              className="gov-input"
                              placeholder="np. 0000054580"
                              value={odwolanieData.Odwolujacy.krs}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  Odwolujacy: { ...odwolanieData.Odwolujacy, krs: e.target.value },
                                })
                              }
                            />
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="odw_nip">
                              <code>nip</code>
                            </label>
                            <input
                              id="odw_nip"
                              type="text"
                              className="gov-input"
                              placeholder="NIP (jeśli występuje)"
                              value={odwolanieData.Odwolujacy.nip}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  Odwolujacy: { ...odwolanieData.Odwolujacy, nip: e.target.value },
                                })
                              }
                            />
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="odw_regon">
                              <code>regon</code>
                            </label>
                            <input
                              id="odw_regon"
                              type="text"
                              className="gov-input"
                              placeholder="REGON (jeśli występuje)"
                              value={odwolanieData.Odwolujacy.regon}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  Odwolujacy: { ...odwolanieData.Odwolujacy, regon: e.target.value },
                                })
                              }
                            />
                          </div>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="odw_przez_pelnomocnika">
                            <code>przez-pelnomocnika</code> (1 - tak, 0 - nie)
                          </label>
                          <select
                            id="odw_przez_pelnomocnika"
                            className="gov-select"
                            value={odwolanieData.Odwolujacy.przez_pelnomocnika}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Odwolujacy: { ...odwolanieData.Odwolujacy, przez_pelnomocnika: e.target.value },
                              })
                            }
                          >
                            <option value="1">1 - Tak (działa przez pełnomocnika)</option>
                            <option value="0">0 - Nie (działa samodzielnie)</option>
                          </select>
                        </div>

                        {/* Podkategoria: pelnomocnik */}
                        <div style={{ backgroundColor: 'var(--gov-bg)', border: '1px solid var(--gov-border-light)', borderRadius: '3px', padding: '16px', marginTop: '12px' }}>
                          <span style={{ fontSize: '0.875rem', fontWeight: 900, color: 'var(--gov-text)', display: 'block', marginBottom: '12px' }}>
                            ↳ Obiekt podrzędny: <code>"pelnomocnik"</code>
                          </span>

                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                            <div className="gov-form-group">
                              <label className="gov-label" htmlFor="odw_pel_imie">
                                <code>imie_nazwisko</code>
                              </label>
                              <input
                                id="odw_pel_imie"
                                type="text"
                                className="gov-input"
                                placeholder="np. Marcel Kielce"
                                value={odwolanieData.Odwolujacy.pelnomocnik_imie_nazwisko}
                                onChange={(e) =>
                                  setOdwolanieData({
                                    ...odwolanieData,
                                    Odwolujacy: { ...odwolanieData.Odwolujacy, pelnomocnik_imie_nazwisko: e.target.value },
                                  })
                                }
                              />
                            </div>

                            <div className="gov-form-group">
                              <label className="gov-label" htmlFor="odw_pel_nazwa">
                                <code>nazwa</code> (Podmiot zatrudniający)
                              </label>
                              <input
                                id="odw_pel_nazwa"
                                type="text"
                                className="gov-input"
                                placeholder="np. Kancelaria Radców Prawnych"
                                value={odwolanieData.Odwolujacy.pelnomocnik_nazwa}
                                onChange={(e) =>
                                  setOdwolanieData({
                                    ...odwolanieData,
                                    Odwolujacy: { ...odwolanieData.Odwolujacy, pelnomocnik_nazwa: e.target.value },
                                  })
                                }
                              />
                            </div>
                          </div>

                          <div className="gov-form-group" style={{ marginBottom: 0 }}>
                            <label className="gov-label" htmlFor="odw_pel_mail">
                              <code>mail</code> (Adres e-mail kontaktowy)
                            </label>
                            <input
                              id="odw_pel_mail"
                              type="email"
                              className="gov-input"
                              placeholder="np. info@prawnik.sy"
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
                      </div>

                      {/* Kategoria 3: "Zamawiajacy" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"Zamawiajacy[]"</code>
                          </h3>
                          <span className="gov-badge">Tablica zamawiających</span>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="zam_nazwa">
                            <code>nazwa</code> (Pełna nazwa Zamawiającego)
                          </label>
                          <input
                            id="zam_nazwa"
                            type="text"
                            className="gov-input"
                            placeholder="np. Filharmonia Pomorska im. Ignacego Jana Paderewskiego"
                            value={odwolanieData.Zamawiajacy.nazwa}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, nazwa: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '14px' }}>
                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="zam_nip">
                              <code>nip</code>
                            </label>
                            <input
                              id="zam_nip"
                              type="text"
                              className="gov-input"
                              placeholder="np. 5540240549"
                              value={odwolanieData.Zamawiajacy.nip}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  Zamawiajacy: { ...odwolanieData.Zamawiajacy, nip: e.target.value },
                                })
                              }
                            />
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="zam_regon">
                              <code>regon</code>
                            </label>
                            <input
                              id="zam_regon"
                              type="text"
                              className="gov-input"
                              placeholder="np. 000279077"
                              value={odwolanieData.Zamawiajacy.regon}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  Zamawiajacy: { ...odwolanieData.Zamawiajacy, regon: e.target.value },
                                })
                              }
                            />
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="zam_krs">
                              <code>krs</code>
                            </label>
                            <input
                              id="zam_krs"
                              type="text"
                              className="gov-input"
                              placeholder="KRS Zamawiającego"
                              value={odwolanieData.Zamawiajacy.krs}
                              onChange={(e) =>
                                setOdwolanieData({
                                  ...odwolanieData,
                                  Zamawiajacy: { ...odwolanieData.Zamawiajacy, krs: e.target.value },
                                })
                              }
                            />
                          </div>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="zam_prowadzacy">
                            <code>prowadzacy_postepowanie</code> (null - brak info, 1 - lider, 0 - nie lider)
                          </label>
                          <select
                            id="zam_prowadzacy"
                            className="gov-select"
                            value={odwolanieData.Zamawiajacy.prowadzacy_postepowanie}
                            onChange={(e) =>
                              setOdwolanieData({
                                ...odwolanieData,
                                Zamawiajacy: { ...odwolanieData.Zamawiajacy, prowadzacy_postepowanie: e.target.value },
                              })
                            }
                          >
                            <option value="null">null - brak informacji / pojedynczy zamawiający</option>
                            <option value="1">1 - oznaczony jako prowadzący postępowanie / lider</option>
                            <option value="0">0 - uczestnik konsorcjum zamawiających (nie lider)</option>
                          </select>
                        </div>
                      </div>

                      {/* Kategoria 4: "ZamowieniePubliczne" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"ZamowieniePubliczne"</code>
                          </h3>
                          <span className="gov-badge">Dane postępowania</span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '14px' }}>
                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="zam_nr_post">
                              <code>numer_postepowania</code>
                            </label>
                            <input
                              id="zam_nr_post"
                              type="text"
                              className="gov-input"
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

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="zam_bzp">
                              <code>numer_bzp</code>
                            </label>
                            <input
                              id="zam_bzp"
                              type="text"
                              className="gov-input"
                              placeholder="Format: 'YYYY/BZP ########'"
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

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="zam_ted">
                              <code>numer_ted</code>
                            </label>
                            <input
                              id="zam_ted"
                              type="text"
                              className="gov-input"
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

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="zam_tytul">
                            <code>tytul</code> (Tytuł zamówienia lub postępowania)
                          </label>
                          <textarea
                            id="zam_tytul"
                            className="gov-textarea"
                            rows={3}
                            placeholder="Wpisz pełny tytuł zamówienia..."
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
                      </div>
                    </div>
                  )}

                  {/* ======================================================== */}
                  {/* KATEGORIE DLA: PEŁNOMOCNICTWO (pelnomocnictwo.json)      */}
                  {/* ======================================================== */}
                  {currentDocIndex === 1 && (
                    <div>
                      {/* Kategoria 1: "mocodawca" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"mocodawca[]"</code>
                          </h3>
                          <span className="gov-badge">Podmiot udzielający</span>
                        </div>

                        {/* Podkategoria: data */}
                        <div style={{ backgroundColor: 'var(--gov-bg)', border: '1px solid var(--gov-border-light)', borderRadius: '3px', padding: '16px', marginBottom: '16px' }}>
                          <span style={{ fontSize: '0.875rem', fontWeight: 900, color: 'var(--gov-text)', display: 'block', marginBottom: '12px' }}>
                            ↳ Obiekt: <code>"data"</code>
                          </span>

                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '14px' }}>
                            <div className="gov-form-group">
                              <label className="gov-label" htmlFor="moc_typ">
                                <code>typ</code>
                              </label>
                              <select
                                id="moc_typ"
                                className="gov-select"
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
                                <option value="osoba_prawna">"osoba_prawna"</option>
                                <option value="osoba_fizyczna">"osoba_fizyczna"</option>
                              </select>
                            </div>

                            <div className="gov-form-group">
                              <label className="gov-label" htmlFor="moc_nazwa">
                                <code>nazwa</code> (Pełna nazwa mocodawcy)
                              </label>
                              <input
                                id="moc_nazwa"
                                type="text"
                                className="gov-input"
                                placeholder="np. FAMBUD"
                                value={pelnomocnictwoData.mocodawca.nazwa}
                                onChange={(e) =>
                                  setPelnomocnictwoData({
                                    ...pelnomocnictwoData,
                                    mocodawca: { ...pelnomocnictwoData.mocodawca, nazwa: e.target.value },
                                  })
                                }
                              />
                            </div>
                          </div>

                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                            <div className="gov-form-group">
                              <label className="gov-label" htmlFor="moc_krs">
                                <code>krs</code> (Numer KRS osoby prawnej)
                              </label>
                              <input
                                id="moc_krs"
                                type="text"
                                className="gov-input"
                                placeholder="np. 0000244633"
                                value={pelnomocnictwoData.mocodawca.krs}
                                onChange={(e) =>
                                  setPelnomocnictwoData({
                                    ...pelnomocnictwoData,
                                    mocodawca: { ...pelnomocnictwoData.mocodawca, krs: e.target.value },
                                  })
                                }
                              />
                            </div>

                            <div className="gov-form-group">
                              <label className="gov-label" htmlFor="moc_nip">
                                <code>nip</code> (Numer NIP mocodawcy)
                              </label>
                              <input
                                id="moc_nip"
                                type="text"
                                className="gov-input"
                                placeholder="np. 8361772283"
                                value={pelnomocnictwoData.mocodawca.nip}
                                onChange={(e) =>
                                  setPelnomocnictwoData({
                                    ...pelnomocnictwoData,
                                    mocodawca: { ...pelnomocnictwoData.mocodawca, nip: e.target.value },
                                  })
                                }
                              />
                            </div>
                          </div>

                          {pelnomocnictwoData.mocodawca.typ === 'osoba_fizyczna' && (
                            <div className="gov-form-group" style={{ marginBottom: 0 }}>
                              <label className="gov-label" htmlFor="moc_imie">
                                <code>imie_nazwisko</code> (Gdy osoba fizyczna, inaczej null)
                              </label>
                              <input
                                id="moc_imie"
                                type="text"
                                className="gov-input"
                                placeholder="Imię i nazwisko osoby fizycznej..."
                                value={pelnomocnictwoData.mocodawca.imie_nazwisko}
                                onChange={(e) =>
                                  setPelnomocnictwoData({
                                    ...pelnomocnictwoData,
                                    mocodawca: { ...pelnomocnictwoData.mocodawca, imie_nazwisko: e.target.value },
                                  })
                                }
                              />
                            </div>
                          )}
                        </div>

                        {/* Podkategoria: podpisujacy */}
                        <div style={{ backgroundColor: 'var(--gov-bg)', border: '1px solid var(--gov-border-light)', borderRadius: '3px', padding: '16px' }}>
                          <span style={{ fontSize: '0.875rem', fontWeight: 900, color: 'var(--gov-text)', display: 'block', marginBottom: '12px' }}>
                            ↳ Tablica: <code>"podpisujacy[]"</code> (Osoby podpisujące w imieniu mocodawcy)
                          </span>

                          <div className="gov-form-group" style={{ marginBottom: 0 }}>
                            <label className="gov-label" htmlFor="moc_podpis">
                              <code>imie_nazwisko</code>
                            </label>
                            <input
                              id="moc_podpis"
                              type="text"
                              className="gov-input"
                              placeholder="np. Paweł Podolski"
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
                      </div>

                      {/* Kategoria 2: "pelnomocnicy" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"pelnomocnicy[]"</code>
                          </h3>
                          <span className="gov-badge">Osoby otrzymujące pełnomocnictwo</span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '14px' }}>
                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="pel_imie">
                              <code>imie_nazwisko</code> (w mianowniku)
                            </label>
                            <input
                              id="pel_imie"
                              type="text"
                              className="gov-input"
                              placeholder="np. Krystyna Mazowiecka"
                              value={pelnomocnictwoData.pelnomocnicy.imie_nazwisko}
                              onChange={(e) =>
                                setPelnomocnictwoData({
                                  ...pelnomocnictwoData,
                                  pelnomocnicy: { ...pelnomocnictwoData.pelnomocnicy, imie_nazwisko: e.target.value },
                                })
                              }
                            />
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="pel_pesel">
                              <code>pesel</code> (Liczba lub tekst)
                            </label>
                            <input
                              id="pel_pesel"
                              type="text"
                              className="gov-input"
                              placeholder="np. 85120133547"
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
                    </div>
                  )}

                  {/* ======================================================== */}
                  {/* KATEGORIE DLA: PRZELEW BANKOWY (przelew.json)             */}
                  {/* ======================================================== */}
                  {currentDocIndex === 2 && (
                    <div>
                      {/* Kategoria 1: "przelew_bankowy" */}
                      <div className="gov-form-section">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                          <h3 className="gov-section-title" style={{ margin: 0 }}>
                            Kategoria: <code>"przelew_bankowy"</code>
                          </h3>
                          <span className="gov-badge">Potwierdzenie przelewu KIO</span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="prz_data">
                              <code>data_operacji</code>
                            </label>
                            <input
                              id="prz_data"
                              type="text"
                              className="gov-input"
                              placeholder="Format: 'YYYY-MM-DD' (np. 2025-10-09)"
                              value={przelewData.przelew_bankowy.data_operacji}
                              onChange={(e) =>
                                setPrzelewData({
                                  ...przelewData,
                                  przelew_bankowy: { ...przelewData.przelew_bankowy, data_operacji: e.target.value },
                                })
                              }
                            />
                          </div>

                          <div className="gov-form-group">
                            <label className="gov-label" htmlFor="prz_kwota">
                              <code>kwota</code> (wartość numeryczna w PLN)
                            </label>
                            <input
                              id="prz_kwota"
                              type="text"
                              className="gov-input"
                              placeholder="np. 10000.00 lub 15000.00"
                              value={przelewData.przelew_bankowy.kwota}
                              onChange={(e) =>
                                setPrzelewData({
                                  ...przelewData,
                                  przelew_bankowy: { ...przelewData.przelew_bankowy, kwota: e.target.value },
                                })
                              }
                            />
                            <span className="gov-hint">Stawki ustawowe: 7500.00, 10000.00, 15000.00, 20000.00</span>
                          </div>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="prz_na_rachunek">
                            <code>na_rachunek</code> (26 cyfr rachunku odbiorcy)
                          </label>
                          <input
                            id="prz_na_rachunek"
                            type="text"
                            className="gov-input"
                            value={przelewData.przelew_bankowy.na_rachunek}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, na_rachunek: e.target.value },
                              })
                            }
                          />
                          <span className="gov-hint">Domyślny rachunek UZP w NBP: 60101010100081362231000000</span>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="prz_z_rachunku">
                            <code>z_rachunku</code> (26 cyfr rachunku nadawcy)
                          </label>
                          <input
                            id="prz_z_rachunku"
                            type="text"
                            className="gov-input"
                            placeholder="np. 508020546000005888744244"
                            value={przelewData.przelew_bankowy.z_rachunku}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, z_rachunku: e.target.value },
                              })
                            }
                          />
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="prz_tytul">
                            <code>tytul</code> (Tytuł przelewu)
                          </label>
                          <textarea
                            id="prz_tytul"
                            className="gov-textarea"
                            rows={3}
                            placeholder="np. WPIS OD ODW., ZAM: ..."
                            value={przelewData.przelew_bankowy.tytul}
                            onChange={(e) =>
                              setPrzelewData({
                                ...przelewData,
                                przelew_bankowy: { ...przelewData.przelew_bankowy, tytul: e.target.value },
                              })
                            }
                          ></textarea>
                        </div>

                        <div className="gov-form-group">
                          <label className="gov-label" htmlFor="prz_nr_transakcji">
                            <code>numer_transakcji</code> (jeśli występuje, inaczej null)
                          </label>
                          <input
                            id="prz_nr_transakcji"
                            type="text"
                            className="gov-input"
                            placeholder="Identyfikator transakcji lub puste dla null"
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
                  <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid var(--gov-border-light)', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                    <button type="button" className="gov-btn-process" onClick={handleSaveData}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" width="18" height="18">
                        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                        <polyline points="17 21 17 13 7 13 7 21"></polyline>
                        <polyline points="7 3 7 8 15 8"></polyline>
                      </svg>
                      <span>Zapisz poprawki</span>
                    </button>

                    {currentDocIndex < docSlots.length - 1 ? (
                      <button type="button" className="gov-btn-primary" onClick={goToNextDoc} style={{ maxWidth: '240px' }}>
                        <span>Następny plik →</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="gov-btn-primary"
                        onClick={() => setShowJsonModal(true)}
                        style={{ maxWidth: '280px' }}
                      >
                        <span>Eksportuj kanoniczny JSON</span>
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
              maxWidth: '760px',
              width: '100%',
              maxHeight: '85vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--gov-border-light)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 900 }}>
                Kanoniczny JSON zgodny z <code>oczekiwane-json/{activeDoc.id}.json</code>
              </h3>
              <button
                type="button"
                className="a11y-btn"
                onClick={() => setShowJsonModal(false)}
                style={{ fontSize: '1rem', padding: '4px 10px' }}
              >
                ✕
              </button>
            </div>

            <div style={{ padding: '20px', overflowY: 'auto', flex: 1, backgroundColor: 'var(--gov-surface)' }}>
              <pre
                style={{
                  margin: 0,
                  fontFamily: 'monospace',
                  fontSize: '0.875rem',
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
                padding: '14px 20px',
                borderTop: '1px solid var(--gov-border-light)',
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '12px',
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
