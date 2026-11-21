/**
 * ZIP reader for browser uploads. Uses the central directory (not local header
 * guessing), so macOS archives with data descriptors extract correctly.
 *
 * Hard caps keep a hostile/corrupt archive from exhausting memory. Only PDF
 * entries get a Blob and an object URL; all other entries are skipped.
 */

export interface ExtractedFile {
  name: string;
  blob: Blob;
  url: string;
  size: number;
}

export const MAX_ZIP_BYTES = 30 * 1024 * 1024;   // 30 MB archiwum
export const MAX_ZIP_ENTRIES = 32;                // macOS dodaje pliki ._ — zostaw margines
export const MAX_PDF_BYTES = 20 * 1024 * 1024;    // 20 MB na jeden PDF

const EOCD = 0x06054b50;
const CENTRAL = 0x02014b50;
const LOCAL = 0x04034b50;

async function readCapped(
  stream: ReadableStream<Uint8Array>,
  limit: number,
  name: string,
): Promise<Uint8Array> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel();
      throw new Error(`Plik ${name} przekracza limit ${limit / 1024 / 1024} MB.`);
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let pos = 0;
  for (const chunk of chunks) {
    out.set(chunk, pos);
    pos += chunk.byteLength;
  }
  return out;
}

export async function extractZipFiles(file: File): Promise<ExtractedFile[]> {
  if (file.size > MAX_ZIP_BYTES) {
    throw new Error(`Archiwum przekracza limit ${MAX_ZIP_BYTES / 1024 / 1024} MB.`);
  }

  const bytes = new Uint8Array(await file.arrayBuffer());
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  // End of central directory: last 64 KiB is enough for normal archives.
  const start = Math.max(0, bytes.length - 65557);
  let eocd = -1;
  for (let i = bytes.length - 4; i >= start; i--) {
    if (view.getUint32(i, true) === EOCD) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error('Nie znaleziono katalogu ZIP (EOCD).');

  const count = view.getUint16(eocd + 10, true);
  if (count > MAX_ZIP_ENTRIES) {
    throw new Error(`Zbyt wiele plików w archiwum (limit ${MAX_ZIP_ENTRIES}).`);
  }
  const centralOffset = view.getUint32(eocd + 16, true);
  const decoder = new TextDecoder('utf-8');
  const files: ExtractedFile[] = [];

  let offset = centralOffset;
  for (let n = 0; n < count; n++) {
    if (offset + 46 > bytes.length || view.getUint32(offset, true) !== CENTRAL) {
      throw new Error('Uszkodzony katalog ZIP.');
    }
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const uncompressedSize = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const name = decoder.decode(bytes.subarray(offset + 46, offset + 46 + nameLength));
    const nextOffset = offset + 46 + nameLength + extraLength + commentLength;

    const isPdf = name.toLowerCase().endsWith('.pdf');
    const isJunk = name.endsWith('/') || name.includes('__MACOSX/') || name.split('/').pop()?.startsWith('._');
    if (!isPdf || isJunk) {
      // Nie twórz Blobów ani object URL dla rzeczy innych niż PDF.
      offset = nextOffset;
      continue;
    }

    if (localOffset + 30 > bytes.length || view.getUint32(localOffset, true) !== LOCAL) {
      throw new Error(`Uszkodzony nagłówek pliku ${name}.`);
    }
    if (compressedSize > MAX_PDF_BYTES || uncompressedSize > MAX_PDF_BYTES) {
      throw new Error(`Plik ${name} przekracza limit ${MAX_PDF_BYTES / 1024 / 1024} MB.`);
    }
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    if (dataStart + compressedSize > bytes.length) {
      throw new Error(`Uszkodzone dane pliku ${name}.`);
    }
    const compressed = bytes.subarray(dataStart, dataStart + compressedSize);

    let fileBytes: Uint8Array;
    if (method === 0) {
      fileBytes = compressed;
    } else if (method === 8 && typeof DecompressionStream !== 'undefined') {
      const stream = new Blob([compressed.slice() as BlobPart]).stream();
      const decompressed = stream.pipeThrough(
        new DecompressionStream('deflate-raw'),
      );
      fileBytes = await readCapped(decompressed, MAX_PDF_BYTES, name);
    } else {
      throw new Error(`Nieobsługiwana kompresja ZIP (${method}) w pliku ${name}.`);
    }
    if (fileBytes.byteLength > MAX_PDF_BYTES) {
      throw new Error(`Plik ${name} przekracza limit ${MAX_PDF_BYTES / 1024 / 1024} MB.`);
    }

    const blob = new Blob([fileBytes.slice() as BlobPart], { type: 'application/pdf' });
    files.push({
      name: name.split('/').pop() || name,
      blob,
      url: URL.createObjectURL(blob),
      size: fileBytes.byteLength,
    });

    offset = nextOffset;
  }

  return files;
}
