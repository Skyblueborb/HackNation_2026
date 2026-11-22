# Odwołania2json — frontend

UI do wgrywania ZIP-a z pismami procesowymi, weryfikacji pól i eksportu JSON.
Docelowe obciążenie: jedna przeglądarka, ZIP z maks. 3 plikami PDF.

## Komendy

```bash
npm install
npm run dev      # http://localhost:3000, proxy /api -> http://localhost:8000

# Backend na innej maszynie (np. L4), bez tunelu:
O2J_API_TARGET=http://<L4-IP>:8000 O2J_API_TOKEN=<token> npm run dev
npm run build    # tsc -b && vite build
npm test         # vitest run
npm run lint     # oxlint
```

## Uwierzytelnianie

Frontend **nie** wysyła żadnego tokenu i nie używa zmiennych `VITE_API_TOKEN`.
Zmienne `VITE_*` są wstawiane do bundle'a i są widoczne dla każdego użytkownika.

- Backend chroni endpointy własnym `API_TOKEN`. Backend nie wystartuje bez
  tokenu, chyba że ustawiono `O2J_DEV_NO_AUTH=1` wyłącznie dla lokalnego dev-u.
  W Dockerze nginx dodaje nagłówek z `O2J_API_TOKEN`; w Vite dev-proxy robi to
  zmienna `O2J_API_TOKEN` (czytana tylko po stronie Node).
- `O2J_API_TARGET` ustawia cel proxy `/api` (domyślnie `http://localhost:8000`).
  Ustaw `http://<L4-IP>:8000`, gdy backend działa na zdalnej maszynie. Ani
  `O2J_API_TARGET`, ani `O2J_API_TOKEN` nie trafiają do bundle'a JS.
- Dev-proxy Vite przekazuje `/api` bez modyfikacji nagłówków. Jeśli wdrożenie
  wymaga tokenu na poziomie proxy, ustaw go po stronie proxy/backu (np. nginx
  lub `docker-compose.yml`), nigdy w kodzie klienta.
- Podgląd PDF używa `<iframe src={blob:...}>` — brak `react-pdf` i workera pdf.js.

## Bezpieczeństwo ZIP

`src/utils/zip.ts` czyta katalog centralny i nakłada limity: 30 MB na archiwum,
32 wpisy, 20 MB na PDF. Tylko wpisy `.pdf` dostają `Blob` i object URL; URL-e
są zwalniane przy re-uploadcie, wczytaniu z bazy i powrocie do menu.

## Testy

`tests/frontend.test.ts` pokrywa parsowanie ZIP-a, kwoty w `buildCanonical`,
`hydrateForms` i wybór klasy dokumentu (LLM -> nazwa pliku).
