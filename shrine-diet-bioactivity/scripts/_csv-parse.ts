/**
 * Minimal RFC-4180 CSV row parser.
 *
 * Used by the CTD loader (and any other script that consumes a flat CSV
 * where field values may contain commas — common in MeSH disease names
 * like "Lymphoma, Mantle-Cell"). Replaces the naive `line.split(',')`
 * pattern that corrupts those rows.
 *
 * Not a full CSV reader (we operate one already-newline-split line at a
 * time). Quoted multi-line fields are NOT supported — CTD doesn't use
 * them, and supporting them would require buffering at the stream layer.
 */

export function parseCsvLine(line: string): string[] {
  if (line.length === 0) {
    return [];
  }

  const fields: string[] = [];
  let buf = '';
  let inQuotes = false;
  let i = 0;

  while (i < line.length) {
    const ch = line[i];

    if (inQuotes) {
      if (ch === '"') {
        // RFC 4180: "" inside a quoted field is a literal quote.
        if (i + 1 < line.length && line[i + 1] === '"') {
          buf += '"';
          i += 2;
          continue;
        }
        // Closing quote.
        inQuotes = false;
        i += 1;
        continue;
      }
      buf += ch;
      i += 1;
      continue;
    }

    if (ch === '"' && buf.trim() === '') {
      // Field-opening quote — at the start of a field, ignoring any
      // leading whitespace (#55). Some CTD producers pad fields after
      // the comma; before this change the leading space prevented the
      // quote from being recognized, and the comma inside the quoted
      // disease name leaked through as a field separator.
      inQuotes = true;
      i += 1;
      continue;
    }

    if (ch === ',') {
      fields.push(buf);
      buf = '';
      i += 1;
      continue;
    }

    // Plain character (including stray unquoted double-quotes — preserve).
    buf += ch;
    i += 1;
  }

  fields.push(buf);
  return fields;
}
