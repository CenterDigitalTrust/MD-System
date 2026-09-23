import express from 'express';
import multer from 'multer';
import cors from 'cors';
import cron from 'node-cron';
import fs from 'fs';
import path from 'path';
import tar from 'tar';

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 4000;
const HOT_STORAGE = path.join(__dirname, '../uploads/hot');
const COLD_STORAGE = path.join(__dirname, '../uploads/cold');

// Убедимся, что директории существуют
if (!fs.existsSync(HOT_STORAGE)) fs.mkdirSync(HOT_STORAGE, { recursive: true });
if (!fs.existsSync(COLD_STORAGE)) fs.mkdirSync(COLD_STORAGE, { recursive: true });

// Настройка Multer (Append-Only)
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, HOT_STORAGE),
    filename: (req, file, cb) => {
        // Уникальное имя файла
        cb(null, `${Date.now()}-${file.originalname}`);
    }
});
const upload = multer({ storage });

// Отдача статики (горячие файлы)
app.use('/files/hot', express.static(HOT_STORAGE));
app.use('/files/cold', express.static(COLD_STORAGE));

// Эндпоинт загрузки
app.post('/upload', upload.single('media'), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: 'No file uploaded' });
    }
    res.status(200).json({
        status: 'success',
        filename: req.file.filename,
        path: `/files/hot/${req.file.filename}`
    });
});

// Эндпоинт получения списка файлов
app.get('/files', (req, res) => {
    const hotFiles = fs.readdirSync(HOT_STORAGE);
    const coldFiles = fs.readdirSync(COLD_STORAGE);
    
    res.json({
        hot: hotFiles.map(f => `/files/hot/${f}`),
        cold: coldFiles.map(f => `/files/cold/${f}`)
    });
});

// Заглушка для удаления (чтобы показать отсутствие эндпоинта)
app.delete('/delete/*', (req, res) => {
    res.status(403).json({ error: 'Append-Only Vault. Deletion is strictly forbidden.' });
});

// Cron-задача: Раз в сутки переносим старые файлы в Cold Storage
// 0 0 * * * = каждый день в 00:00
cron.schedule('0 0 * * *', async () => {
    console.log('[Cron] Running Cold Storage Worker...');
    const now = Date.now();
    const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;
    
    const hotFiles = fs.readdirSync(HOT_STORAGE);
    const filesToArchive: string[] = [];
    
    for (const file of hotFiles) {
        const filePath = path.join(HOT_STORAGE, file);
        const stats = fs.statSync(filePath);
        if (now - stats.mtimeMs > SEVEN_DAYS_MS) {
            filesToArchive.push(file);
        }
    }
    
    if (filesToArchive.length > 0) {
        const archiveName = `archive-${Date.now()}.tar.gz`;
        const archivePath = path.join(COLD_STORAGE, archiveName);
        
        try {
            await tar.c(
                {
                    gzip: true,
                    file: archivePath,
                    cwd: HOT_STORAGE
                },
                filesToArchive
            );
            
            console.log(`[Cron] Created archive: ${archiveName} with ${filesToArchive.length} files.`);
            
            // Удаляем файлы из hot storage только после успешной архивации
            for (const file of filesToArchive) {
                fs.unlinkSync(path.join(HOT_STORAGE, file));
            }
        } catch (error) {
            console.error('[Cron] Archiving failed:', error);
        }
    } else {
        console.log('[Cron] No old files to archive.');
    }
});

app.listen(PORT, () => {
    console.log(`Independent Vault running on port ${PORT}`);
});
