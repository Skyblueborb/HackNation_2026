import { describe, expect, it } from 'vitest';
import {
  buildCanonical,
  classFromLlm,
  classifyName,
  emptyForms,
  makeDoc,
  renumberTitles,
} from '../src/logic';
import { hydrateForms } from '../src/hydrate';
import { extractZipFiles, MAX_ZIP_BYTES, MAX_ZIP_ENTRIES } from '../src/utils/zip';

// Minimal stored (method 0) ZIP writer — enough to exercise the central-directory reader.
const u16 = (n: number) => [n & 0xff, (n >> 8) & 0xff];
const u32 = (n: number) => [n & 0xff, (n >>> 8) & 0xff, (n >>> 16) & 0xff, (n >>> 24) & 0xff];

function makeZip(entries: Array<{ name: string; bytes: Uint8Array }>): Uint8Array {
  const locals: number[] = [];
  const centrals: number[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Array.from(new TextEncoder().encode(entry.name));
    const size = entry.bytes.length;
    locals.push(
      ...u32(0x04034b50), ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
      ...u32(0), ...u32(size), ...u32(size), ...u16(name.length), ...u16(0),
      ...name, ...Array.from(entry.bytes),
    );
    centrals.push(
      ...u32(0x02014b50), ...u16(20), ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
      ...u32(0), ...u32(size), ...u32(size), ...u16(name.length), ...u16(0), ...u16(0),
      ...u16(0), ...u16(0), ...u32(0), ...u32(offset), ...name,
    );
    offset += 30 + name.length + size;
  }
  const eocd = [
    ...u32(0x06054b50), ...u16(0), ...u16(0), ...u16(entries.length), ...u16(entries.length),
    ...u32(centrals.length), ...u32(offset), ...u16(0),
  ];
  return new Uint8Array([...locals, ...centrals, ...eocd]);
}

describe('zip parsing', () => {
  it('returns only PDF entries with a blob and object URL', async () => {
    const bytes = makeZip([
      { name: 'notes.txt', bytes: new TextEncoder().encode('not a pdf') },
      { name: 'scan.pdf', bytes: new TextEncoder().encode('%PDF-1.4 test') },
    ]);
    const files = await extractZipFiles(new File([bytes], 'case.zip'));
    expect(files).toHaveLength(1);
    expect(files[0].name).toBe('scan.pdf');
    expect(files[0].size).toBe(13);
    expect(files[0].blob.type).toBe('application/pdf');
    expect(files[0].url).toMatch(/^blob:/);
    URL.revokeObjectURL(files[0].url);
  });

  it('rejects a corrupt archive with a readable error', async () => {
    await expect(extractZipFiles(new File([new Uint8Array([1, 2, 3])], 'bad.zip')))
      .rejects.toThrow(/EOCD/i);
  });

  it('caps archive size and entry count', async () => {
    const small = makeZip([{ name: 'a.pdf', bytes: new Uint8Array([1]) }]);
    const big = new File([small], 'big.zip');
    Object.defineProperty(big, 'size', { value: MAX_ZIP_BYTES + 1 });
    await expect(extractZipFiles(big)).rejects.toThrow(/limit/i);

    const many = makeZip(
      Array.from({ length: MAX_ZIP_ENTRIES + 1 }, (_, i) => ({
        name: `f${i}.pdf`,
        bytes: new Uint8Array([1]),
      })),
    );
    await expect(extractZipFiles(new File([many], 'many.zip'))).rejects.toThrow(/limit/i);
  });
});

describe('buildCanonical amounts', () => {
  const kwota = (raw: string): unknown => {
    const data = emptyForms();
    data.przelew.przelew_bankowy.kwota = raw;
    return (buildCanonical('przelew', data) as any).przelew_bankowy.kwota;
  };

  it('strips whitespace before replacing the comma', () => {
    expect(kwota('10 000,50')).toBe(10000.5);
    expect(kwota(' 1 234,5 ')).toBe(1234.5);
  });

  it('keeps dot decimals and nulls empty input', () => {
    expect(kwota('10000.00')).toBe(10000);
    expect(kwota('   ')).toBeNull();
    expect(kwota('')).toBeNull();
  });
});

describe('hydrateForms', () => {
  it('maps canonical JSON arrays into flat form fields', () => {
    const forms = hydrateForms([{
      doc_class: 'odwolanie',
      canonical_json: {
        OdwolanieKIO: { data: '13.10.2025', czynnosc_powod_id: 4 },
        Odwolujacy: [{ nazwa: 'STRABAG', 'przez-pelnomocnika': 1, pelnomocnik: { mail: 'a@b.pl' } }],
        Zamawiajacy: [{ prowadzacy_postepowanie: 0 }],
      },
    }]);
    expect(forms.odwolanie.OdwolanieKIO.data).toBe('13.10.2025');
    expect(forms.odwolanie.OdwolanieKIO.czynnosc_powod_id).toBe('4');
    expect(forms.odwolanie.Odwolujacy['przez-pelnomocnika']).toBeUndefined();
    expect(forms.odwolanie.Odwolujacy.przez_pelnomocnika).toBe('1');
    expect(forms.odwolanie.Odwolujacy.pelnomocnik_mail).toBe('a@b.pl');
    expect(forms.odwolanie.Zamawiajacy.prowadzacy_postepowanie).toBe('0');
  });

  it('maps a transfer and returns nulls for no documents', () => {
    const forms = hydrateForms([{
      doc_class: 'przelew',
      canonical_json: { przelew_bankowy: { kwota: 10000.5, z_rachunku: '501010' } },
    }]);
    expect(forms.przelew.przelew_bankowy.kwota).toBe('10000.5');
    expect(hydrateForms([])).toEqual({ odwolanie: null, pelnomocnictwo: null, przelew: null });
  });
});

describe('class selection', () => {
  it('uses LLM class when valid and maps backend przelew name', () => {
    expect(classFromLlm('odwolanie')).toBe('odwolanie');
    expect(classFromLlm('pelnomocnictwo')).toBe('pelnomocnictwo');
    expect(classFromLlm('potwierdzenie_przelewu')).toBe('przelew');
    expect(classFromLlm('nieznany')).toBeNull();
    expect(classFromLlm(null)).toBeNull();
  });

  it('falls back to filename for generic names', () => {
    expect(classifyName(' scan_001.pdf ')).toBe('odwolanie');
    expect(classifyName('przelew.pdf')).toBe('przelew');
  });

  it('renumbers titles after a class change', () => {
    const slots = [makeDoc('odwolanie', 1), makeDoc('przelew', 1), makeDoc('przelew', 2)];
    slots[0].doc_class = 'przelew';
    expect(renumberTitles(slots).map((s) => s.title)).toEqual([
      'Przelew #1', 'Przelew #2', 'Przelew #3',
    ]);
  });
});
