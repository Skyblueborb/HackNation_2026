import { useState, useRef, useEffect } from 'react';
import type { ExtractedFile } from './utils/zip';
import { createZipArchive, type ZipFileInput } from './utils/zipWriter';
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
  id: 'odwolanie' | 'pelnomocnictwo' | 'przelew' | 'nierozpoznany';
  title: string;
  categoryLabel: string;
  defaultFilename: string;
  folderName?: string;
  relativePath?: string;
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
  const [stage, setStage] = useState<'upload' | 'splitscreen' | 'done'>('upload');
  const [selectedFolder, setSelectedFolder] = useState<{ name: string; files: File[] } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const [currentDocIndex, setCurrentDocIndex] = useState(0);
  const [docSlots, setDocSlots] = useState<DocumentSlot[]>([
    {
      id: 'odwolanie',
      title: 'Odwołanie do KIO',
      categoryLabel: 'Odwołanie',
      defaultFilename: 'odwolanie.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'pelnomocnictwo',
      title: 'Pełnomocnictwo',
      categoryLabel: 'Pełnomocnictwo',
      defaultFilename: 'pelnomocnictwo.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'przelew',
      title: 'Potwierdzenie przelewu',
      categoryLabel: 'Przelew',
      defaultFilename: 'przelew.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'odwolanie',
      title: 'Odwołanie_sprawa2.pdf',
      categoryLabel: 'Odwołanie',
      defaultFilename: 'Odwołanie_sprawa2.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'pelnomocnictwo',
      title: 'Pełnomocnictwo_substytucyjne.pdf',
      categoryLabel: 'Pełnomocnictwo',
      defaultFilename: 'Pełnomocnictwo_substytucyjne.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'przelew',
      title: 'Potwierdzenie_opłaty.pdf',
      categoryLabel: 'Przelew',
      defaultFilename: 'Potwierdzenie_opłaty.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'odwolanie',
      title: 'Odwołanie_KIO_3.pdf',
      categoryLabel: 'Odwołanie',
      defaultFilename: 'Odwołanie_KIO_3.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'pelnomocnictwo',
      title: 'Pełnomocnictwo_ogólne.pdf',
      categoryLabel: 'Pełnomocnictwo',
      defaultFilename: 'Pełnomocnictwo_ogólne.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'przelew',
      title: 'Przelew_wpis_KIO.pdf',
      categoryLabel: 'Przelew',
      defaultFilename: 'Przelew_wpis_KIO.pdf',
      folderName: 'Sprawa',
    },
    {
      id: 'nierozpoznany',
      title: 'Pismo_przewodnie_KIO.pdf',
      categoryLabel: 'Nierozpoznany',
      defaultFilename: 'Pismo_przewodnie_KIO.pdf',
      folderName: 'Inne dokumenty',
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

  const tabsScrollRef = useRef<HTMLDivElement>(null);
  const tabButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const activeBtn = tabButtonRefs.current[currentDocIndex];
    if (activeBtn) {
      activeBtn.scrollIntoView({
        behavior: 'smooth',
        inline: 'nearest',
        block: 'nearest',
      });
    }
  }, [currentDocIndex]);

  const scrollTabs = (direction: 'left' | 'right') => {
    if (tabsScrollRef.current) {
      tabsScrollRef.current.scrollBy({
        left: direction === 'left' ? -220 : 220,
        behavior: 'smooth',
      });
    }
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

  const handleFolderSelection = (fileList: FileList | File[]) => {
    const rawFiles = Array.from(fileList);
    if (rawFiles.length === 0) return;

    // Pobierz nazwę folderu głównego
    let rootFolder = 'Paczka_dokumentów';
    const firstRel = (rawFiles[0] as unknown as { webkitRelativePath?: string }).webkitRelativePath;
    if (firstRel) {
      const parts = firstRel.split('/');
      if (parts.length > 1) {
        rootFolder = parts[0];
      }
    }

    setErrorMessage(null);
    setSelectedFolder({ name: rootFolder, files: rawFiles });
  };

  const startProcessing = async () => {
    if (!selectedFolder || selectedFolder.files.length === 0) return;

    const files = selectedFolder.files;
    // Mapowanie plików na DocumentSlot z uwzględnieniem podfolderów
    const newSlots: DocumentSlot[] = [];

    files.forEach((file) => {
      const relPath = (file as unknown as { webkitRelativePath?: string }).webkitRelativePath || file.name;
      const parts = relPath.split('/').filter(Boolean);
      
      // Podfolder wewnątrz głównego katalogu (np. "Sprawa/odwolanie.pdf")
      let folderName = 'Sprawa';
      if (parts.length >= 3) {
        // np. GlownyFolder/Sprawa_1/plik.pdf
        folderName = parts[1].replace(/[_]/g, ' ').replace(/\s*\d+$/, '').trim() || parts[1];
      } else if (parts.length === 2) {
        // np. Sprawa_1/plik.pdf
        folderName = parts[0].replace(/[_]/g, ' ').replace(/\s*\d+$/, '').trim() || parts[0];
      }

      const lowerName = file.name.toLowerCase();
      let docClass: 'odwolanie' | 'pelnomocnictwo' | 'przelew' | 'nierozpoznany' = 'nierozpoznany';
      let categoryLabel = 'Nierozpoznany';

      if (lowerName.includes('odwol') || lowerName.includes('odwoł') || lowerName.includes('appeal')) {
        docClass = 'odwolanie';
        categoryLabel = 'Odwołanie';
      } else if (lowerName.includes('pelnom') || lowerName.includes('pełnom') || lowerName.includes('power')) {
        docClass = 'pelnomocnictwo';
        categoryLabel = 'Pełnomocnictwo';
      } else if (lowerName.includes('przel') || lowerName.includes('oplat') || lowerName.includes('opłat') || lowerName.includes('trans')) {
        docClass = 'przelew';
        categoryLabel = 'Przelew';
      }

      const blobUrl = URL.createObjectURL(file);
      const extractedFile: ExtractedFile = {
        name: file.name,
        blob: file,
        url: blobUrl,
        size: file.size,
      };

      // Wyznacz pełną relatywną ścieżkę wewnątrz głównego folderu
      let relativePath = file.name;
      if (parts.length >= 2) {
        // Jeśli plik ma ścieżkę GłównyFolder/Podfolder/plik.pdf -> Podfolder/plik.pdf
        relativePath = parts.slice(1).join('/');
      }

      newSlots.push({
        id: docClass,
        title: `${newSlots.length + 1}. ${file.name}`,
        categoryLabel,
        defaultFilename: file.name,
        folderName,
        relativePath,
        file: extractedFile,
      });
    });

    if (newSlots.length > 0) {
      setDocSlots(newSlots);
    }
    setCurrentDocIndex(0);
    setStage('splitscreen');
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

  // Generowanie kanonicznego JSON zgodnego 1:1 z oczekiwane-json
  const getCanonicalJson = (index: number = currentDocIndex) => {
    const slot = docSlots[index];
    const docType = slot ? slot.id : (index === 0 ? 'odwolanie' : index === 1 ? 'pelnomocnictwo' : index === 2 ? 'przelew' : 'nierozpoznany');

    if (docType === 'odwolanie') {
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
    } else if (docType === 'pelnomocnictwo') {
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
    } else if (docType === 'przelew') {
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
    } else {
      // Dla nierozpoznanego typu dokumentu zwracane są puste klamerki {}
      return {};
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

  // Pobranie spakowanego folderu ze wszystkimi podfolderami i plikami .json
  const downloadAllJsonArchive = () => {
    const zipFiles: ZipFileInput[] = [];

    docSlots.forEach((slot, index) => {
      // Nazwa pliku z rozszerzeniem zmienionym na .json
      const origFilename = slot.file?.name || slot.defaultFilename;
      const jsonFilename = origFilename.replace(/\.[^/.]+$/, '') + '.json';

      // Ścieżka relatywna wewnątrz paczki zachowująca podfoldery
      let relPath = '';
      if (slot.relativePath) {
        // Zastąp rozszerzenie na .json w ścieżce relatywnej
        relPath = slot.relativePath.replace(/\.[^/.]+$/, '') + '.json';
      } else {
        const folder = (slot.folderName || 'Sprawa').replace(/\s+/g, '_');
        relPath = `${folder}/${jsonFilename}`;
      }

      zipFiles.push({
        path: relPath,
        content: JSON.stringify(getCanonicalJson(index), null, 2),
      });
    });

    const zipBlob = createZipArchive(zipFiles);
    const archiveName = `${selectedFolder?.name || 'odwolania2json'}.zip`;
    const url = URL.createObjectURL(zipBlob);
    const dlAnchor = document.createElement('a');
    dlAnchor.setAttribute('href', url);
    dlAnchor.setAttribute('download', archiveName);
    dlAnchor.click();
    URL.revokeObjectURL(url);
  };

  // Zapisuje wszystkie dokumenty i przechodzi do podsumowania z pobraniem JSON
  const handleSaveAllAndFinish = async () => {
    await saveAll();
    downloadAllJsonArchive();
    setStage('done');
  };

  return (
    <>
      {/* 1. GŁÓWNA ZAWARTOŚĆ */}
      <main className="gov-main">
        {/* ======================================================== */}
        {/* WIDOK 1: EKRAN WCZYTYWANIA FOLDERU Z DOKUMENTAMI        */}
        {/* ======================================================== */}
        {stage === 'upload' && (
          <div className="gov-container">
            <div className="service-header">
              <h1 className="service-title">Odwołania2json</h1>
            </div>

            <p className="service-description">
              Wybierz folder zawierający podfoldery ze sprawami odwoławczymi. System automatycznie pogrupuje pliki,
              rozpozna rodzaj każdego pisma i powiąże ze sobą dokumenty należące do tych samych spraw.
            </p>

            <section className="upload-section" aria-label="Przesyłanie dokumentacji">
              <input
                type="file"
                ref={folderInputRef}
                className="file-input-hidden"
                // @ts-expect-error webkitdirectory to standardowe rozszerzenie przeglądarek do wyboru całego folderu
                webkitdirectory=""
                directory=""
                multiple
                onChange={(e) => {
                  if (e.target.files && e.target.files.length > 0) {
                    handleFolderSelection(e.target.files);
                  }
                }}
              />

              <button
                type="button"
                className="gov-btn-primary"
                onClick={() => folderInputRef.current?.click()}
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
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
                <span>Załaduj folder</span>
              </button>

              <div
                className={`dropzone ${dragOver ? 'dragover' : ''}`}
                role="button"
                tabIndex={0}
                aria-label="Upuść folder tutaj lub naciśnij Enter, aby wybrać z dysku"
                onClick={() => folderInputRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    folderInputRef.current?.click();
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
                  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    handleFolderSelection(e.dataTransfer.files);
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
                <p className="dropzone-label">lub upuść folder tutaj</p>
                <p className="dropzone-hint">Akceptowany format: folder z podfolderami spraw (np. Sprawa 1, Sprawa 2)</p>
              </div>

              {errorMessage && (
                <div className="status-box visible is-error" role="status" aria-live="polite">
                  <p className="status-title">Nieprawidłowy folder lub pliki</p>
                  <p className="status-meta">{errorMessage}</p>
                </div>
              )}

              {selectedFolder && !errorMessage && (
                <div className="status-box visible is-success" role="status" aria-live="polite">
                  <p className="status-title">Wybrano folder: {selectedFolder.name}</p>
                  <p className="status-meta">
                    Liczba plików: {selectedFolder.files.length} ({formatFileSize(selectedFolder.files.reduce((acc, f) => acc + f.size, 0))}) • Gotowy do analizy i grupowania według spraw
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
                        setSelectedFolder(null);
                        if (folderInputRef.current) folderInputRef.current.value = '';
                      }}
                    >
                      Usuń folder
                    </button>
                  </div>
                </div>
              )}
            </section>

            <div className="gov-info-note">
              <strong>Informacja o przetwarzaniu:</strong> Wewnątrz folderu głównego mogą znajdować się podfoldery z poszczególnymi sprawami. System automatycznie powiąże pliki ze sobą.
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* WIDOK 2: SPLIT-SCREEN (CZYSTY, ESTETYCZNY DLA LUDZI)     */}
        {/* ======================================================== */}
        {stage === 'splitscreen' && (
          <div className="gov-container-wide">
            {/* Pasek nawigacyjny: Slider zakładek ze strzałkami, Poprzedni/Następny plik, Zapisz wszystko */}
            <div className="gov-doc-nav-bar">
              {/* Sekcja slidera zakładek ze strzałkami po lewej i prawej */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1, minWidth: 0 }}>
                <button
                  type="button"
                  className="slider-arrow-btn"
                  onClick={() => scrollTabs('left')}
                  title="Przewiń listę plików w lewo"
                  aria-label="Przewiń w lewo"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width="16" height="16">
                    <polyline points="15 18 9 12 15 6"></polyline>
                  </svg>
                </button>

                {/* Zakładki z nazwami wszystkich plików pogrupowane w podfoldery/sprawy z możliwością poziomego scrollowania */}
                <div className="doc-files-scroll-container" ref={tabsScrollRef} role="tablist">
                  {(() => {
                    // Pogrupuj indeksy slotów według folderName (z zachowaniem kolejności)
                    const groups: { folderName: string; indices: number[] }[] = [];
                    docSlots.forEach((slot, index) => {
                      const fName = slot.folderName || 'Sprawa';
                      const lastGroup = groups[groups.length - 1];
                      if (lastGroup && lastGroup.folderName === fName) {
                        lastGroup.indices.push(index);
                      } else {
                        groups.push({ folderName: fName, indices: [index] });
                      }
                    });

                    return groups.map((grp) => {
                      const isFolderActive = grp.indices.includes(currentDocIndex);
                      return (
                        <div
                          key={grp.folderName + grp.indices[0]}
                          className={`doc-folder-group ${isFolderActive ? 'is-active-folder' : ''}`}
                        >
                          {grp.indices.map((idx) => {
                            const slot = docSlots[idx];
                            const filename = slot.file?.name || slot.defaultFilename;
                            const isActive = idx === currentDocIndex;
                            return (
                              <button
                                key={slot.id + idx}
                                ref={(el) => { tabButtonRefs.current[idx] = el; }}
                                type="button"
                                role="tab"
                                aria-selected={isActive}
                                className={`doc-file-tab-btn ${isActive ? 'active' : ''}`}
                                onClick={() => {
                                  setCurrentDocIndex(idx);
                                  window.scrollTo({ top: 0, behavior: 'smooth' });
                                }}
                                title={filename}
                              >
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ flexShrink: 0 }}>
                                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                  <polyline points="14 2 14 8 20 8"></polyline>
                                </svg>
                                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {filename}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      );
                    });
                  })()}
                </div>

                <button
                  type="button"
                  className="slider-arrow-btn"
                  onClick={() => scrollTabs('right')}
                  title="Przewiń listę plików w prawo"
                  aria-label="Przewiń w prawo"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width="16" height="16">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                </button>
              </div>

              {/* Przyciski nawigacji: Poprzedni plik, Następny plik po prawej stronie od nazw plików */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                <button
                  type="button"
                  className="clean-btn-outline-lg"
                  onClick={goToPrevDoc}
                  disabled={currentDocIndex === 0}
                  style={{ opacity: currentDocIndex === 0 ? 0.4 : 1, cursor: currentDocIndex === 0 ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}
                >
                  Poprzedni plik
                </button>

                <button
                  type="button"
                  className="clean-btn-outline-lg"
                  onClick={goToNextDoc}
                  disabled={currentDocIndex === docSlots.length - 1}
                  style={{ opacity: currentDocIndex === docSlots.length - 1 ? 0.4 : 1, cursor: currentDocIndex === docSlots.length - 1 ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}
                >
                  Następny plik
                </button>
              </div>

              <div style={{ flexShrink: 0 }}>
                <button
                  type="button"
                  className="gov-btn-process"
                  style={{ padding: '9px 20px', fontSize: '0.9375rem', whiteSpace: 'nowrap' }}
                  onClick={handleSaveAllAndFinish}
                >
                  Zapisz wszystko
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
                  <span className="gov-badge">Dokument {currentDocIndex + 1} z {docSlots.length}</span>
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
                        {activeDoc.defaultFilename}
                      </h3>
                      <p style={{ margin: '0 0 14px', maxWidth: '340px', fontSize: '0.875rem', color: '#8c939d' }}>
                        W tym oknie wyświetla się plik <strong>{activeDoc.defaultFilename}</strong> z wgranego folderu.
                      </p>
                      <span className="preview-doc-btn">Podgląd dokumentu</span>
                    </div>
                  )}
                </div>
              </div>

              {/* --- PRAWA STRONA: CZYSTE, PROSTE POLA BEZ PRZYTŁACZANIA (IMAGE 2 STYLE) --- */}
              <div className="gov-split-pane">
                <div className="gov-pane-header">
                  <div>
                    <h2 className="gov-pane-title">
                      {activeDoc.file?.name || activeDoc.defaultFilename}
                    </h2>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className="clean-btn-outline"
                      onClick={fillSampleGoldData}
                      title="Wstaw przykładowe dane z wzorca"
                    >
                      Wstaw przykład
                    </button>
                    <button
                      type="button"
                      className="clean-btn-outline"
                      onClick={clearCurrentData}
                      title="Wyczyść wszystkie pola"
                    >
                      Wyczyść
                    </button>
                    <button
                      type="button"
                      className="clean-btn-outline"
                      onClick={loadFromBackend}
                      title="Pobierz wyniki z bazy danych backendu"
                    >
                      Wczytaj z bazy
                    </button>
                    <button
                      type="button"
                      className="clean-btn-outline"
                      onClick={() => setShowJsonModal(true)}
                    >
                      Podgląd JSON
                    </button>
                  </div>
                </div>

                <div className="gov-form-wrapper">
                  {/* Wybór typu dokumentu (przed kategoriami) */}
                  <div className="clean-row" style={{ paddingBottom: '14px', marginBottom: '14px', borderBottom: '1px solid var(--gov-border-light)' }}>
                    <label
                      htmlFor="doc_type_select"
                      className="clean-label"
                    >
                      Typ dokumentu:
                    </label>
                    <select
                      id="doc_type_select"
                      className="clean-select"
                      value={activeDoc.id}
                      onChange={(e) => {
                        const newType = e.target.value as 'odwolanie' | 'pelnomocnictwo' | 'przelew' | 'nierozpoznany';
                        const typeLabels: Record<string, string> = {
                          odwolanie: `${currentDocIndex + 1}. Odwołanie do KIO`,
                          pelnomocnictwo: `${currentDocIndex + 1}. Pełnomocnictwo`,
                          przelew: `${currentDocIndex + 1}. Potwierdzenie przelewu`,
                          nierozpoznany: `${currentDocIndex + 1}. Nierozpoznany typ`,
                        };
                        const categoryLabels: Record<string, string> = {
                          odwolanie: 'Odwołanie',
                          pelnomocnictwo: 'Pełnomocnictwo',
                          przelew: 'Przelew',
                          nierozpoznany: 'Nierozpoznany',
                        };
                        const newSlots = [...docSlots];
                        newSlots[currentDocIndex] = {
                          ...newSlots[currentDocIndex],
                          id: newType,
                          title: typeLabels[newType] || `${currentDocIndex + 1}. Dokument`,
                          categoryLabel: categoryLabels[newType] || 'Inny',
                        };
                        setDocSlots(newSlots);
                      }}
                    >
                      <option value="odwolanie">Odwołanie do KIO</option>
                      <option value="pelnomocnictwo">Pełnomocnictwo</option>
                      <option value="przelew">Potwierdzenie przelewu</option>
                      <option value="nierozpoznany">Nierozpoznany typ</option>
                    </select>
                  </div>

                  {/* ======================================================== */}
                  {/* DOKUMENT 1: ODWOŁANIE DO KIO                             */}
                  {/* ======================================================== */}
                  {activeDoc.id === 'odwolanie' && (
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
                  {activeDoc.id === 'pelnomocnictwo' && (
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
                  {activeDoc.id === 'przelew' && (
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

                  {/* ======================================================== */}
                  {/* DOKUMENT: NIEROZPOZNANY TYP                              */}
                  {/* ======================================================== */}
                  {activeDoc.id === 'nierozpoznany' && (
                    <div className="clean-form-section">
                      <div className="clean-section-header">
                        <h3 className="clean-section-title">
                          Nierozpoznany typ dokumentu
                        </h3>
                        <span className="gov-badge" style={{ borderColor: '#6c757d', color: '#6c757d' }}>
                          Brak szablonu
                        </span>
                      </div>
                      <div
                        style={{
                          padding: '24px 16px',
                          textAlign: 'center',
                          backgroundColor: '#f8fafc',
                          borderRadius: '4px',
                          border: '1px dashed #cbd5e1',
                          color: 'var(--gov-text-muted)',
                        }}
                      >
                        <p style={{ margin: '0 0 8px', fontSize: '0.9375rem', fontWeight: 600 }}>
                          Ten dokument został oznaczony jako nierozpoznany typ.
                        </p>
                        <p style={{ margin: 0, fontSize: '0.8125rem' }}>
                          Wybierz typ powyżej (odwołanie, pełnomocnictwo lub potwierdzenie przelewu), aby wyświetlić i edytować odpowiednie kategorie pól.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Dolny pasek akcji formularza */}
                  <div style={{ marginTop: '20px', paddingTop: '14px', borderTop: '1px solid var(--gov-border-light)', display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'flex-end' }}>
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

        {/* ======================================================== */}
        {/* WIDOK 3: EKRAN GOTOWE / PODSUMOWANIE (W STYLU WIDOKU 1) */}
        {/* ======================================================== */}
        {stage === 'done' && (
          <div className="gov-container">
            <div className="service-header">
              <h1 className="service-title">Gotowe! Rozpoczęto pobieranie paczki folderów JSON</h1>
            </div>

            <p className="service-description">
              Paczka <strong>{selectedFolder?.name || 'odwolania2json'}.zip</strong> zawierająca podfoldery z plikami <strong>.json</strong> została pomyślnie wygenerowana i pobrana na Twój komputer.
              Możesz teraz pobrać ją ponownie, wrócić do edycji danych lub przesłać kolejną paczkę dokumentów.
            </p>

            <section style={{ backgroundColor: '#ffffff', padding: '24px 0 12px 0' }}>
              <div>
                <h2 style={{ fontSize: '1.0625rem', fontWeight: 700, margin: '0 0 14px', color: 'var(--gov-text)' }}>
                  Ilości przetworzonych plików:
                </h2>
                <div style={{ maxWidth: '420px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.9375rem', borderBottom: '1px solid rgba(0,0,0,0.06)', paddingBottom: '6px' }}>
                    <span style={{ color: 'var(--gov-text-muted)' }}>Odwołanie do KIO:</span>
                    <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--gov-text)' }}>
                      {docSlots.filter(s => s.id === 'odwolanie' || s.title.toLowerCase().includes('odwoł')).length}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.9375rem', borderBottom: '1px solid rgba(0,0,0,0.06)', paddingBottom: '6px' }}>
                    <span style={{ color: 'var(--gov-text-muted)' }}>Pełnomocnictwo:</span>
                    <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--gov-text)' }}>
                      {docSlots.filter(s => s.id === 'pelnomocnictwo' || s.title.toLowerCase().includes('pełnomoc')).length}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.9375rem', borderBottom: '1px solid rgba(0,0,0,0.06)', paddingBottom: '6px' }}>
                    <span style={{ color: 'var(--gov-text-muted)' }}>Potwierdzenie przelewu:</span>
                    <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--gov-text)' }}>
                      {docSlots.filter(s => s.id === 'przelew' || s.title.toLowerCase().includes('przelew')).length}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.9375rem', paddingTop: '2px' }}>
                    <span style={{ color: 'var(--gov-text-muted)' }}>Nierozpoznany typ:</span>
                    <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--gov-text)' }}>
                      {docSlots.filter(s => s.id === 'nierozpoznany' || s.title.toLowerCase().includes('nierozpoznany')).length}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '28px' }}>
                  <button
                    type="button"
                    className="gov-btn-process"
                    onClick={() => {
                      setStage('upload');
                      setSelectedFolder(null);
                      if (folderInputRef.current) folderInputRef.current.value = '';
                    }}
                  >
                    <span>Prześlij kolejne pliki</span>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width="18" height="18">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                  </button>

                  <button
                    type="button"
                    className="gov-btn-secondary"
                    onClick={downloadAllJsonArchive}
                  >
                    Pobierz ponownie foldery JSON
                  </button>

                  <button
                    type="button"
                    className="gov-btn-secondary"
                    onClick={() => setStage('splitscreen')}
                  >
                    Wróć do edycji
                  </button>
                </div>
              </div>
            </section>

            <div className="gov-info-note">
              <strong>Informacja:</strong> Wszelkie wprowadzone poprawki w formularzach zostały uwzględnione w wygenerowanym i pobranym pliku JSON.
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
