import express from 'express';
import cors from 'cors';
import { MerkleTree } from 'merkletreejs';
import SHA256 from 'crypto-js/sha256';
import sqlite3 from 'sqlite3';
import { open, Database } from 'sqlite';
import { Connection, Keypair, PublicKey } from '@solana/web3.js';
import * as anchor from '@coral-xyz/anchor';
import fs from 'fs';

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 3000;
const BATCH_WINDOW_MS = 10000;

// Solana Setup
const SOLANA_RPC = process.env.SOLANA_RPC || 'http://127.0.0.1:8899';
const PROGRAM_ID = new PublicKey("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

// В реальной системе приватный ключ агрегатора будет лежать в защищенном .env
const AGGREGATOR_KP = Keypair.generate(); // Заглушка для тестов

const connection = new Connection(SOLANA_RPC, 'confirmed');

let hashPool: { device_id: string, pubkey: string, hash: string, signature: string, data: string }[] = [];
let db: Database;

async function setupDB() {
    db = await open({
        filename: './leaves.db',
        driver: sqlite3.Database
    });
    
    await db.exec(`
        CREATE TABLE IF NOT EXISTS merkle_leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_hash TEXT,
            leaf_hash TEXT,
            device_id TEXT,
            pubkey TEXT,
            signature TEXT,
            raw_data TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    `);
}

async function processBatch() {
    if (hashPool.length === 0) return;
    
    const currentBatch = [...hashPool];
    hashPool = [];
    
    console.log(`[Batcher] Processing window... Collected ${currentBatch.length} hashes.`);
    
    const leaves = currentBatch.map(item => item.hash);
    const tree = new MerkleTree(leaves, SHA256, { sortPairs: true });
    const root = tree.getRoot().toString('hex');
    
    console.log(`[Batcher] Merkle Root generated: ${root}`);
    
    for (const item of currentBatch) {
        await db.run(
            `INSERT INTO merkle_leaves (root_hash, leaf_hash, device_id, pubkey, signature, raw_data) VALUES (?, ?, ?, ?, ?, ?)`,
            [root, item.hash, item.device_id, item.pubkey, item.signature, item.data]
        );
    }
    
    try {
        // Симуляция отправки транзакции через Anchor
        // const wallet = new anchor.Wallet(AGGREGATOR_KP);
        // const provider = new anchor.AnchorProvider(connection, wallet, {});
        // const idl = ...; 
        // const program = new anchor.Program(idl, PROGRAM_ID, provider);
        // const [pda] = PublicKey.findProgramAddressSync([Buffer.from("merkle_record"), AGGREGATOR_KP.publicKey.toBuffer()], PROGRAM_ID);
        // const tx = await program.methods.anchorRoot(Array.from(Buffer.from(root, 'hex')))
        //     .accounts({ merkleRecord: pda, aggregator: AGGREGATOR_KP.publicKey })
        //     .rpc();
        
        // Для демо-стенда генерируем фейковую сигнатуру Solana, если нода недоступна
        const tx_signature = "simulated_tx_" + Date.now();
        console.log(`[Anchor] Root ${root} successfully anchored. Tx: ${tx_signature}`);
    } catch (e) {
        console.error(`[Anchor] Anchoring failed:`, e);
    }
}

setInterval(() => {
    processBatch().catch(console.error);
}, BATCH_WINDOW_MS);

app.post('/api/v1/submit-hash', (req, res) => {
    const { device_id, pubkey, data, signature } = req.body;
    
    const leafHash = SHA256(data).toString();
    
    hashPool.push({
        device_id,
        pubkey,
        hash: leafHash,
        signature,
        data // Сохраняем сырые данные (frame_hash + timestamp + geo)
    });
    
    res.status(200).json({ status: 'queued' });
});

app.get('/api/proof/:frame_hash', async (req, res) => {
    const { frame_hash } = req.params;
    
    try {
        // Ищем лист, в котором raw_data начинается с frame_hash
        const leafRec = await db.get(
            `SELECT * FROM merkle_leaves WHERE raw_data LIKE ?`, 
            [`${frame_hash}%`]
        );
        
        if (!leafRec) {
            return res.status(404).json({ error: 'Frame not found in Aggregator' });
        }
        
        const root_hash = leafRec.root_hash;
        
        // Достаем весь батч
        const records = await db.all(
            `SELECT leaf_hash FROM merkle_leaves WHERE root_hash = ?`, 
            [root_hash]
        );
        
        const leaves = records.map((r: any) => r.leaf_hash);
        const tree = new MerkleTree(leaves, SHA256, { sortPairs: true });
        
        const proof = tree.getProof(leafRec.leaf_hash);
        
        res.json({ 
            root_hash,
            leaf_hash: leafRec.leaf_hash,
            proof,
            signature: leafRec.signature,
            pubkey: leafRec.pubkey,
            raw_data: leafRec.raw_data, // Содержит GEO и Time
            device_id: leafRec.device_id
        });
    } catch (error) {
        res.status(500).json({ error: 'Database error' });
    }
});

setupDB().then(() => {
    app.listen(PORT, () => {
        console.log(`Merkle Aggregator listening on port ${PORT}`);
    });
}).catch(console.error);
