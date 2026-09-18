import { createIcons, icons } from 'lucide';
import QRCode from 'qrcode';
window.refreshIcons = () => createIcons({ icons });
window.QRCode = QRCode;
