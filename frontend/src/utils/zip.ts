/**
 * ZIP reader for browser uploads. Uses the central directory (not local header
 * guessing), so macOS archives with data descriptors extract correctly.
 */

export interface ExtractedFile {
  name: string;
  blob: Blob;
  url: string;
  size: number;
}

const EOCD = 0x06054b50;
const CENTRAL = 0x02014b50;
const LOCAL = 0x04034b50;

export async function extractZipFiles(file: File): Promise<ExtractedFile[]> {
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
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const name = decoder.decode(bytes.subarray(offset + 46, offset + 46 + nameLength));

    if (
      !name.endsWith('/') &&
      !name.includes('__MACOSX/') &&
      !name.split('/').pop()?.startsWith('._')
    ) {
      if (view.getUint32(localOffset, true) !== LOCAL) {
        throw new Error(`Uszkodzony nagłówek pliku ${name}.`);
      }
      const localNameLength = view.getUint16(localOffset + 26, true);
      const localExtraLength = view.getUint16(localOffset + 28, true);
      const dataStart = localOffset + 30 + localNameLength + localExtraLength;
      const compressed = bytes.subarray(
        dataStart,
        dataStart + compressedSize,
      );

      let fileBytes: Uint8Array;
      if (method === 0) {
        fileBytes = compressed;
      } else if (method === 8 && typeof DecompressionStream !== 'undefined') {
        const stream = new Blob([compressed.slice() as BlobPart]).stream();
        const decompressed = stream.pipeThrough(
          new DecompressionStream('deflate-raw'),
        );
        fileBytes = new Uint8Array(await new Response(decompressed).arrayBuffer());
      } else {
        throw new Error(`Nieobsługiwana kompresja ZIP (${method}) w pliku ${name}.`);
      }

      const mime = name.toLowerCase().endsWith('.pdf')
        ? 'application/pdf'
        : 'application/octet-stream';
      const blob = new Blob([fileBytes.slice() as BlobPart], { type: mime });
      files.push({
        name: name.split('/').pop() || name,
        blob,
        url: URL.createObjectURL(blob),
        size: fileBytes.byteLength,
      });
    }

    offset += 46 + nameLength + extraLength + commentLength;
  }

  return files;
}
