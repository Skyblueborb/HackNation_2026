/**
 * Lekki, bezbiblioteczny ekstraktor plików ZIP dla przeglądarek.
 * Wykorzystuje natywne API DecompressionStream('deflate-raw') wspierane
 * we wszystkich współczesnych przeglądarkach (Chrome 80+, Firefox 102+, Safari 16.4+).
 */

export interface ExtractedFile {
  name: string;
  blob: Blob;
  url: string;
  size: number;
}

export async function extractZipFiles(file: File): Promise<ExtractedFile[]> {
  const buffer = await file.arrayBuffer();
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const files: ExtractedFile[] = [];

  let offset = 0;
  const len = view.byteLength;

  while (offset + 30 < len) {
    // Sprawdź sygnaturę Local File Header: 0x04034b50 ("PK\x03\x04")
    const sig = view.getUint32(offset, true);
    if (sig !== 0x04034b50) {
      break;
    }

    const flags = view.getUint16(offset + 6, true);
    const method = view.getUint16(offset + 8, true);
    let compSize = view.getUint32(offset + 18, true);
    let uncompSize = view.getUint32(offset + 22, true);
    const nameLen = view.getUint16(offset + 26, true);
    const extraLen = view.getUint16(offset + 28, true);

    const nameBytes = bytes.subarray(offset + 30, offset + 30 + nameLen);
    const filename = new TextDecoder('utf-8').decode(nameBytes);

    const dataStart = offset + 30 + nameLen + extraLen;

    if (compSize === 0 && uncompSize === 0 && (flags & 0x08)) {
      let nextHeader = dataStart;
      while (nextHeader + 4 < len) {
        const nextSig = view.getUint32(nextHeader, true);
        if (nextSig === 0x08074b50) {
          compSize = view.getUint32(nextHeader + 4, true);
          uncompSize = view.getUint32(nextHeader + 8, true);
          break;
        } else if (nextSig === 0x04034b50 || nextSig === 0x02014b50) {
          compSize = nextHeader - dataStart;
          uncompSize = compSize;
          break;
        }
        nextHeader++;
      }
    }

    const compData = bytes.subarray(dataStart, dataStart + compSize);

    try {
      let fileBytes: Uint8Array;
      if (method === 0) {
        fileBytes = compData;
      } else if (method === 8) {
        if (typeof DecompressionStream !== 'undefined') {
          const ds = new DecompressionStream('deflate-raw');
          const decompressedStream = new Response(compData.slice()).body?.pipeThrough(ds);
          const decompressedBuffer = await new Response(decompressedStream).arrayBuffer();
          fileBytes = new Uint8Array(decompressedBuffer);
        } else {
          fileBytes = compData;
        }
      } else {
        fileBytes = compData;
      }

      if (!filename.endsWith('/')) {
        const mime = filename.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'application/octet-stream';
        const blob = new Blob([fileBytes.slice() as unknown as BlobPart], { type: mime });
        const url = URL.createObjectURL(blob);
        files.push({
          name: filename.split('/').pop() || filename,
          blob,
          url,
          size: fileBytes.byteLength,
        });
      }
    } catch (e) {
      console.warn(`Nie udało się zdekompresować pliku ${filename}:`, e);
    }

    offset = dataStart + compSize;
    if (offset + 4 < len && view.getUint32(offset, true) === 0x08074b50) {
      offset += 16;
    }
  }

  return files;
}
