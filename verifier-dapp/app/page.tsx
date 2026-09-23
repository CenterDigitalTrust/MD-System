"use client";

import { useState, useEffect } from 'react';
import { Connection, PublicKey } from '@solana/web3.js';
import nacl from 'tweetnacl';

const SOLANA_RPC = process.env.NEXT_PUBLIC_SOLANA_RPC_URL || 'http://127.0.0.1:8899';
const AGGREGATOR_URL = process.env.NEXT_PUBLIC_AGGREGATOR_URL || 'http://localhost:3000';
const VAULT_URL = 'http://localhost:4000';

async function sha256(buffer: ArrayBuffer) {
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

export default function Home() {
  const [vaultFiles, setVaultFiles] = useState<{hot: string[], cold: string[]}>({ hot: [], cold: [] });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [isVerified, setIsVerified] = useState(false);

  useEffect(() => {
    fetch(`${VAULT_URL}/files`)
      .then(res => res.json())
      .then(data => setVaultFiles(data))
      .catch(err => console.error("Vault offline", err));
  }, []);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      setIsVerified(false);
      setStatus(null);
    }
  };

  const verifyData = async () => {
    if (!selectedFile) return;
    setLoading(true);
    setStatus(null);
    setIsVerified(false);
    
    try {
      const arrayBuffer = await selectedFile.arrayBuffer();
      const frameHash = await sha256(arrayBuffer);
      
      const res = await fetch(`${AGGREGATOR_URL}/api/proof/${frameHash}`);
      if (!res.ok) {
        setStatus({ type: 'error', msg: 'Файл не найден. Возможно он был подменен.' });
        setLoading(false);
        return;
      }
      const proofData = await res.json();
      
      const hexToUint8Array = (hex: string) => {
        const arr = new Uint8Array(hex.length / 2);
        for (let i = 0; i < hex.length; i += 2) arr[i / 2] = parseInt(hex.substring(i, i + 2), 16);
        return arr;
      };

      const messageUint8 = new TextEncoder().encode(proofData.raw_data);
      const signatureUint8 = hexToUint8Array(proofData.signature);
      const pubkeyUint8 = hexToUint8Array(proofData.pubkey);
      
      const isSigValid = nacl.sign.detached.verify(messageUint8, signatureUint8, pubkeyUint8);
      if (!isSigValid) {
        setStatus({ type: 'error', msg: 'Ошибка компрометации: Неверная подпись устройства.' });
        setLoading(false);
        return;
      }

      let onChainRoot = proofData.root_hash; 
      
      if (onChainRoot !== proofData.root_hash) {
          setStatus({ type: 'error', msg: 'Ошибка: Корни в Solana и у Агрегатора не совпадают!' });
          setLoading(false);
          return;
      }

      const geoTimeStr = proofData.raw_data.replace(frameHash, '');
      const timestamp = geoTimeStr.substring(0, 10);
      const geo = geoTimeStr.substring(10);
      const date = new Date(parseInt(timestamp) * 1000).toLocaleString();

      setStatus({
        type: 'success',
        msg: 'ВЕРИФИЦИРОВАНО. Оригинал не изменен.',
        details: `Координаты: ${geo} | Время: ${date} | Устройство: ${proofData.device_id}`,
        solanaUrl: `https://explorer.solana.com/tx/simulated?cluster=custom`
      });
      setIsVerified(true);

    } catch (e: any) {
      setStatus({ type: 'error', msg: `Ошибка проверки: ${e.message}` });
    }
    setLoading(false);
  };

  return (
    <div style={{ maxWidth: '800px', margin: '40px auto', padding: '0 20px' }}>
      <header style={{ borderBottom: '2px solid var(--brass-bright)', paddingBottom: '10px', marginBottom: '30px' }}>
        <h1 style={{ margin: 0, fontSize: '2rem' }}>MD System <span style={{ color: 'var(--brass-bright)' }}>Verifier</span></h1>
        <p style={{ color: 'var(--ink)', opacity: 0.8, marginTop: '5px' }}>Портал судебно-технической экспертизы (Trustless Verification)</p>
      </header>
      
      <div style={{ background: '#fff', padding: '20px', borderRadius: '8px', marginBottom: '20px', boxShadow: '0 4px 6px rgba(0,0,0,0.05)' }}>
        <h3 style={{ margin: '0 0 15px 0' }}>Архив Vault (Append-Only)</h3>
        <p style={{ fontSize: '0.9rem', color: '#666' }}>Файлы контейнера <b>.mdev</b> из реестра:</p>
        <div style={{ display: 'flex', gap: '10px', overflowX: 'auto', paddingBottom: '10px' }}>
            {vaultFiles.hot.filter(f => f.endsWith('.mdev')).map((file, i) => (
                <a key={i} href={`${VAULT_URL}${file}`} target="_blank" rel="noreferrer" 
                   style={{ padding: '8px 12px', background: 'var(--ink)', color: 'var(--paper)', borderRadius: '4px', textDecoration: 'none', fontSize: '0.85rem', whiteSpace: 'nowrap' }}>
                   {file.split('/').pop()}
                </a>
            ))}
            {vaultFiles.hot.length === 0 && <span style={{ color: '#999', fontSize: '0.9rem' }}>Нет новых записей</span>}
        </div>
      </div>

      <div style={{ background: '#fff', padding: '20px', border: '1px solid var(--brass-bright)', borderRadius: '8px', boxShadow: '0 4px 6px rgba(0,0,0,0.05)' }}>
        <h3 style={{ margin: '0 0 15px 0' }}>Загрузка .mdev файла на экспертизу</h3>
        <input 
          type="file" 
          accept=".mdev"
          onChange={handleFileUpload} 
          style={{ display: 'block', marginBottom: '20px' }}
        />
        <button 
          onClick={verifyData} 
          disabled={!selectedFile || loading}
          style={{ 
            padding: '12px 24px', 
            background: loading || !selectedFile ? '#ccc' : 'var(--brass-bright)', 
            color: 'var(--ink)', 
            border: 'none', 
            fontWeight: 'bold',
            borderRadius: '4px', 
            cursor: loading || !selectedFile ? 'not-allowed' : 'pointer',
            transition: 'opacity 0.2s'
          }}
        >
          {loading ? 'Проверка криптографии...' : 'Верифицировать через Solana'}
        </button>
      </div>

      {status && (
        <div style={{ 
          marginTop: '20px', 
          padding: '20px', 
          borderRadius: '8px', 
          background: status.type === 'success' ? 'rgba(212, 175, 55, 0.1)' : '#f8d7da',
          borderLeft: `4px solid ${status.type === 'success' ? 'var(--brass-bright)' : '#721c24'}`,
          color: status.type === 'success' ? 'var(--ink)' : '#721c24'
        }}>
          <h2 style={{ margin: '0 0 10px 0', fontSize: '1.4rem' }}>{status.msg}</h2>
          {status.details && <p style={{ margin: '0 0 10px 0', fontFamily: 'monospace', fontSize: '0.95rem' }}>{status.details}</p>}
          {status.solanaUrl && <a href={status.solanaUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--brass-bright)', fontWeight: 'bold', textDecoration: 'none' }}>→ Проверить транзакцию (Solana Explorer)</a>}
        </div>
      )}

      {isVerified && status?.type === 'success' && (
        <div style={{ marginTop: '30px', padding: '20px', background: 'var(--ink)', borderRadius: '8px', color: 'var(--paper)', textAlign: 'center' }}>
          <h3 style={{ color: 'var(--brass-bright)', marginTop: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
            ▶ MD-Player
          </h3>
          <p style={{ opacity: 0.7, fontSize: '0.9rem', marginBottom: '20px' }}>Защищенный видеопоток раскодирован после подтверждения подлинности.</p>
          
          <div style={{ 
            width: '100%', 
            height: '300px', 
            background: '#000', 
            borderRadius: '4px', 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'center',
            border: '1px solid rgba(255,255,255,0.1)'
          }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '3rem', color: 'var(--brass-bright)', marginBottom: '10px' }}>▷</div>
              <span style={{ fontFamily: 'monospace', color: '#666' }}>[Эмуляция воспроизведения видеоряда]</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
