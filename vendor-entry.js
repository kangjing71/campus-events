// Bundled by esbuild into static/vendor.js (npm run build).
// Third-party bundles and their licenses (full texts formerly in licenses/):
//   lucide    ISC  — https://github.com/lucide-icons/lucide (icons)
//   qrcode    MIT  — https://github.com/soldair/node-qrcode (QR codes)
//   dijkstrajs MIT — bundled dependency of qrcode
import { createIcons, icons } from 'lucide';
import QRCode from 'qrcode';
window.refreshIcons = () => createIcons({ icons });
window.QRCode = QRCode;
