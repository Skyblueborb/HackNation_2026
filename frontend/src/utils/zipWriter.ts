/**
 * Lekki generator plików ZIP zgodny ze specyfikacją PKZIP 2.0 (Stored - bez kompresji / z zachowaniem UTF-8).
 * Nie wymaga zewnętrznych zależności i działa w 100% lokalnie w przeglądarce.
 */

export interface ZipFileInput {
  path: string; // np. "Sprawa_1/odwolanie.json"
  content: string; // zawartość tekstowa (JSON)
}

function crc32(bytes: Uint8Array): number {
  let crc = 0 ^ -1;
  for (let i = 0; i < bytes.length; i++) {
    crc = (crc >>> 8) ^ table[(crc ^ bytes[i]) & 0xff];
  }
  return (crc ^ -1) >>> 0;
}

const table = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let c = i;
  for (let j = 0; j < 8; j++) {
    c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  }
  table[i] = c;
}

export function createZipArchive(files: ZipFileInput[]): Blob {
  const parts: Uint8Array[] = [];
  const cdParts: Uint8Array[] = [];
  const encoder = new TextEncoder();

  let offset = 0;

  for (const f of files) {
    const filenameBytes = encoder.encode(f.path.replace(/\\/g, '/'));
    const contentBytes = encoder.encode(f.content);
    const crc = crc32(contentBytes);
    const size = contentBytes.length;

    // Local file header (30 bajtów)
    const lfh = new Uint8Array(30);
    const lfhView = new DataView(lfh.buffer);
    lfhView.setUint32(0, 0x04034b50, true); // Local header signature
    lfhView.setUint16(4, 20, true);         // Version needed to extract (2.0)
    lfhView.setUint16(6, 0x0800, true);     // Flags: bit 11 = UTF-8
    lfhView.setUint16(8, 0, true);          // Compression method (0 = Stored)
    lfhView.setUint16(10, 0, true);         // Mod time
    lfhView.setUint16(12, 0, true);         // Mod date
    lfhView.setUint32(14, crc, true);       // CRC-32
    lfhView.setUint32(18, size, true);      // Compressed size
    lfhView.setUint32(22, size, true);      // Uncompressed size
    lfhView.setUint16(26, filenameBytes.length, true); // Filename length
    lfhView.setUint16(28, 0, true);         // Extra field length

    parts.push(lfh);
    parts.push(filenameBytes);
    parts.push(contentBytes);

    // Central directory header (46 bajtów)
    const cdh = new Uint8Array(46);
    const cdhView = new DataView(cdh.buffer);
    cdhView.setUint32(0, 0x02014b50, true); // Central directory signature
    cdhView.setUint16(4, 20, true);         // Version made by
    cdhView.setUint16(6, 20, true);         // Version needed
    cdhView.setUint16(8, 0x0800, true);     // Flags: bit 11 = UTF-8
    cdhView.setUint16(10, 0, true);         // Compression method (0 = Stored)
    cdhView.setUint16(12, 0, true);         // Mod time
    cdhView.setUint16(14, 0, true);         // Mod date
    cdhView.setUint32(16, crc, true);       // CRC-32
    cdhView.setUint32(20, size, true);      // Compressed size
    cdhView.setUint32(24, size, true);      // Uncompressed size
    cdhView.setUint16(28, filenameBytes.length, true); // Filename length
    cdhView.setUint16(30, 0, true);         // Extra field length
    cdhView.setUint16(32, 0, true);         // File comment length
    cdhView.setUint16(34, 0, true);         // Disk number start
    cdhView.setUint16(36, 0, true);         // Internal file attributes
    cdhView.setUint32(38, 0, true);         // External file attributes
    cdhView.setUint32(42, offset, true);    // Relative offset of local header

    cdParts.push(cdh);
    cdParts.push(filenameBytes);

    offset += lfh.length + filenameBytes.length + contentBytes.length;
  }

  const cdOffset = offset;
  let cdSize = 0;
  for (const p of cdParts) {
    cdSize += p.length;
  }

  // End of central directory record (22 bajty)
  const eocd = new Uint8Array(22);
  const eocdView = new DataView(eocd.buffer);
  eocdView.setUint32(0, 0x06054b50, true); // EOCD signature
  eocdView.setUint16(4, 0, true);          // Disk number
  eocdView.setUint16(6, 0, true);          // Disk with CD
  eocdView.setUint16(8, files.length, true);  // Number of entries on this disk
  eocdView.setUint16(10, files.length, true); // Total entries
  eocdView.setUint32(12, cdSize, true);    // Central directory size
  eocdView.setUint32(16, cdOffset, true);  // Offset of start of CD
  eocdView.setUint16(20, 0, true);         // Comment length

  const allBytes = [...parts, ...cdParts, eocd];
  return new Blob(allBytes as BlobPart[], { type: 'application/zip' });
}
