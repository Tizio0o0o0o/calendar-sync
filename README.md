# Calendar Sync

Questo progetto sincronizza eventi da più calendari Google in un calendario master e aggiorna un calendario "tempo libero" in base agli slot disponibili.

## Funzionalità
- Sincronizza eventi da vari calendari sorgente in un calendario master
- Aggiorna automaticamente il calendario del tempo libero con gli slot disponibili
- Gestione automatica di credenziali e token OAuth2
- Log dettagliato delle operazioni in `calendar_sync.log`

## Requisiti
- Python 3.8+
- Google Calendar API abilitata
- File di configurazione `config.json` con i parametri dei calendari
- File di credenziali `credentials.json` scaricato dalla Google Cloud Console

## Installazione
1. Crea un ambiente virtuale:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Installa le dipendenze:
   ```bash
   pip install -r requirements.txt
   ```
3. Inserisci i file `config.json` e `credentials.json` nella cartella principale.

## Utilizzo
Esegui lo script principale:
```bash
python main.py
```

## Configurazione
- Modifica `config.json` per impostare i calendari sorgente, il calendario master, il calendario tempo libero, la fascia oraria e le ore lavorative.

## File importanti
- `main.py`: Script principale
- `config.json`: Configurazione dei calendari
- `credentials.json`: Credenziali OAuth2
- `token.json`: Token di autenticazione generato automaticamente
- `calendar_sync.log`: Log delle operazioni

## Note
- I file sensibili e la cartella `venv` sono esclusi dal controllo versione tramite `.gitignore`.
- Per rigenerare il token, elimina `token.json` e riesegui lo script.

## Licenza
Questo progetto è privato e non ha una licenza open source specificata.
