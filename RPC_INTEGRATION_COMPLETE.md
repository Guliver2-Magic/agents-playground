# RPC Integration - Implémentation Complète

**Date**: 2026-01-03
**Status**: ✅ Implémentation terminée, test manuel requis

---

## 🎯 Objectif

Permettre l'invocation directe des 10 function tools depuis le frontend du playground LiveKit, sans passer par le LLM, via le système RPC de LiveKit.

---

## ✅ Implémentation Réalisée

### 1. Backend - RPC Handlers

**Fichier**: `/opt/stacks/c3po-v3/pipecat-service/app/agents/rpc_handlers.py` (367 lignes)

Création de 10 méthodes RPC wrapping les function tools:

| RPC Method | Function Tool | Description |
|------------|---------------|-------------|
| `get_weather` | `get_weather()` | Météo pour une localisation |
| `find_restaurant` | `find_restaurant()` | Recherche de restaurants par cuisine |
| `get_news` | `get_news()` | Dernières nouvelles par topic |
| `search_calendar` | `search_calendar()` | Recherche d'événements du calendrier |
| `control_home` | `control_home()` | Contrôle domotique (lumières, scènes) |
| `make_phone_call` | `make_phone_call()` | Passer un appel téléphonique |
| `control_music` | `control_music()` | Contrôle de la musique |
| `ask_about_buddy` | `ask_about_buddy()` | Questions sur Buddy le chien |
| `get_expert_advice` | `get_expert_advice()` | Conseils d'expert (tennis, horlogerie, VFX) |
| `order_delivery` | `order_delivery()` | Commander une livraison de nourriture |

**Pattern utilisé**:
```python
@local_participant.register_rpc_method("get_weather")
async def rpc_get_weather(data: RpcInvocationData) -> str:
    try:
        payload = json.loads(data.payload)
        location = payload.get("location")
        units = payload.get("units", "metric")

        if not location:
            raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, "Missing 'location' parameter")

        result = await get_weather(location=location, units=units)

        return json.dumps({
            "success": True,
            "data": result
        })

    except Exception as e:
        logger.error(f"RPC get_weather error: {e}", exc_info=True)
        raise RpcError(RpcError.ErrorCode.APPLICATION_ERROR, str(e))
```

**Caractéristiques**:
- ✅ Parsing JSON du payload
- ✅ Validation des paramètres requis
- ✅ Gestion d'erreurs avec RpcError
- ✅ Logging complet
- ✅ Retour JSON standardisé `{success: boolean, data: any}`

### 2. Agent Registration

**Fichier**: `/opt/stacks/agents-playground/test_agent.py` (modifié lignes 55-57)

```python
from app.agents.rpc_handlers import register_rpc_methods

# Register RPC methods for direct function tool invocation from frontend
register_rpc_methods(ctx.room.local_participant)
logger.info("✓ RPC methods registered")
```

**Log de confirmation**:
```
2026-01-03 02:53:12 - __main__ - INFO - ✓ RPC methods registered
```

### 3. Frontend - RPC Panel UI

**Fichier**: `/opt/stacks/agents-playground/src/components/playground/RpcPanel.tsx` (282 lignes)

**Composants**:

#### A. Grille de sélection (10 boutons)
```tsx
<div className="grid grid-cols-2 gap-2">
  {FUNCTION_TOOLS.map((tool) => (
    <button
      key={tool.name}
      onClick={() => handleToolSelect(tool.name)}
      className={selectedTool === tool.name ? "border-cyan-500 bg-cyan-500/10" : "border-gray-800"}
    >
      {tool.label}  // 🌤️ Weather, 🍕 Restaurant, 📰 News, etc.
    </button>
  ))}
</div>
```

#### B. Formulaires dynamiques
Chaque tool a un formulaire spécifique avec:
- **Champs texte** (`<input type="text">`) pour locations, queries, contacts
- **Sélecteurs** (`<select>`) pour units (metric/imperial), actions (play/pause/next), etc.
- **Champs numériques** (`<input type="number">`) pour count, volume
- **Validation visuelle** avec astérisque rouge (*) pour champs requis

**Exemple**: Tool "Weather"
```tsx
fields: [
  { name: "location", label: "Location", type: "text", placeholder: "Montreal", required: true },
  { name: "units", label: "Units", type: "select", options: ["metric", "imperial"], default: "metric" },
]
```

#### C. Logique d'invocation RPC
```tsx
const handleCall = async () => {
  // Build payload from form values
  const payload: Record<string, any> = {};
  tool.fields.forEach((field: any) => {
    const value = formValues[field.name] || field.default || "";
    if (value) {
      // Special handling for comma-separated lists
      if (field.name === "items") {
        payload[field.name] = value.split(",").map((item: string) => item.trim());
      } else if (field.type === "number") {
        payload[field.name] = parseInt(value, 10);
      } else {
        payload[field.name] = value;
      }
    }
  });

  setRpcPayload(JSON.stringify(payload));

  // Call RPC via LiveKit SDK
  const result = await handleRpcCall();  // → room.localParticipant.performRpc()
  setRpcResult({ success: true, data: result });
};
```

#### D. Affichage des résultats
```tsx
{rpcResult && (
  <>
    <div className="text-xs text-gray-500">
      {rpcResult.success ? "✓ Result" : "✗ Error"}
    </div>
    <div className={rpcResult.success ? "border-green-500 text-green-400" : "border-red-500 text-red-400"}>
      <pre className="whitespace-pre-wrap">
        {JSON.stringify(rpcResult.data, null, 2)}
      </pre>
    </div>
  </>
)}
```

### 4. Integration dans Playground.tsx

**Fichier**: `/opt/stacks/agents-playground/src/components/playground/Playground.tsx` (lignes 451-460)

```tsx
{connectionState === ConnectionState.Connected && agent.isConnected && (
  <RpcPanel
    config={config}
    rpcMethod={rpcMethod}
    rpcPayload={rpcPayload}
    setRpcMethod={setRpcMethod}
    setRpcPayload={setRpcPayload}
    handleRpcCall={handleRpcCall}
  />
)}
```

**RPC Call Handler** (lignes 229-245):
```tsx
const handleRpcCall = useCallback(async () => {
  if (!agent.internal.agentParticipant) {
    throw new Error("No agent or room available");
  }

  const response = await session.room.localParticipant.performRpc({
    destinationIdentity: agent.internal.agentParticipant.identity,
    method: rpcMethod,
    payload: rpcPayload,
  });
  return response;
}, [session.room.localParticipant, rpcMethod, rpcPayload, agent.internal.agentParticipant]);
```

---

## 🔧 Build & Deploy

### Build Status
```bash
cd /opt/stacks/agents-playground
npm run build
```

**Résultat**: ✅ Build successful (15.3s)
```
Route (pages)                                Size  First Load JS
┌ ○ / (621 ms)                             236 kB         334 kB
├   /_app                                     0 B        97.7 kB
├ ○ /404                                    180 B        97.9 kB
└ ƒ /api/token                                0 B        97.7 kB
```

### Dev Server
```bash
npm run dev
```

**Status**: ✅ Running on port 3004
```
   ▲ Next.js 15.5.6
   - Local:        http://localhost:3004
   - Network:      http://192.168.150.219:3004
 ✓ Ready in 2.6s
```

### Voice Agent
```bash
cd /opt/stacks/agents-playground
source .venv/bin/activate
LIVEKIT_URL=ws://localhost:7880 \
LIVEKIT_API_KEY=devkey \
LIVEKIT_API_SECRET=NtujbRjs7xfrS6ERkA6rXH-SyKfGXMCU_8FR0wexU-I \
VOICE_PERSONA=aria \
VOICE_LANGUAGE=fr \
OPENAI_API_KEY="sk-proj-..." \
python3 test_agent.py dev
```

**Status**: ✅ Running (PID 3418412)

---

## 🧪 Test Manuel

### 1. Démarrer les services

```bash
# Terminal 1 - Voice Agent
cd /opt/stacks/agents-playground
source .venv/bin/activate
LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=NtujbRjs7xfrS6ERkA6rXH-SyKfGXMCU_8FR0wexU-I VOICE_PERSONA=aria VOICE_LANGUAGE=fr OPENAI_API_KEY="sk-proj-..." python3 test_agent.py dev > /tmp/voice_agent.log 2>&1 &

# Terminal 2 - Playground
cd /opt/stacks/agents-playground
npm run dev

# Terminal 3 - Monitor logs
tail -f /tmp/voice_agent.log
```

### 2. Ouvrir le playground

```
http://localhost:3004
```

### 3. Se connecter

1. Cliquer sur **"Connect"** (bouton cyan en haut à droite)
2. Attendre la connexion (status passe de "Disconnected" à "Connected")
3. Vérifier que l'agent est connecté (Identity: `agent-id_...`)

### 4. Tester les RPC Methods

#### Scénario 1: Weather (Météo)
1. Scroller dans le panneau de droite jusqu'à **"Function Tools"**
2. Cliquer sur **"🌤️ Weather"**
3. Remplir:
   - Location: `Montreal`
   - Units: `metric` (par défaut)
4. Cliquer sur **"Call 🌤️ Weather"**
5. Vérifier le résultat JSON:
```json
{
  "success": true,
  "data": {
    "temperature": 18,
    "condition": "ensoleillé",
    "location": "Montreal"
  }
}
```

#### Scénario 2: Restaurant (Recherche)
1. Cliquer sur **"🍕 Restaurant"**
2. Remplir:
   - Query: `Italian restaurant`
   - Location: `Montreal` (optionnel)
3. Cliquer sur **"Call 🍕 Restaurant"**
4. Vérifier les résultats (liste de restaurants)

#### Scénario 3: Buddy (Questions sur le chien)
1. Cliquer sur **"🐕 Buddy"**
2. Remplir:
   - Question: `Where is Buddy?`
3. Cliquer sur **"Call 🐕 Buddy"**
4. Vérifier la localisation de Buddy

#### Scénario 4: Home Control (Domotique)
1. Cliquer sur **"🏠 Home"**
2. Remplir:
   - Action: `turn_on`
   - Target: `bedroom lights`
   - Value: `50` (optionnel, pour dimming)
3. Cliquer sur **"Call 🏠 Home"**
4. Vérifier la confirmation

### 5. Vérifier les logs

**Agent logs**:
```bash
tail -20 /tmp/voice_agent.log
```

Rechercher:
```
RPC get_weather error: ...
RPC find_restaurant error: ...
✓ TTS completed: ...
```

**Console browser** (F12 → Console):
```
[LiveKit] RPC method called: get_weather
[LiveKit] RPC response: {"success":true,"data":{...}}
```

---

## 📊 Statistiques

### Code ajouté/modifié

| Fichier | Lignes | Type | Description |
|---------|--------|------|-------------|
| `rpc_handlers.py` | 367 | Nouveau | 10 RPC method wrappers |
| `test_agent.py` | +3 | Modifié | Import & registration |
| `RpcPanel.tsx` | 282 | Remplacé | UI complète avec 10 tools |
| `Playground.tsx` | +16 | Modifié | Integration RPC panel |

**Total**: ~670 lignes de code

### Fonctionnalités

- ✅ 10 RPC methods (1 par function tool)
- ✅ 10 boutons UI (grille 2x5)
- ✅ 10 formulaires dynamiques
- ✅ Validation des champs requis
- ✅ Parsing spécialisé (comma-separated lists, numbers)
- ✅ Affichage des résultats (JSON formaté)
- ✅ Gestion d'erreurs (RpcError)
- ✅ Logging complet

---

## 🐛 Problèmes Connus

### 1. Playground ne se connecte pas automatiquement

**Symptôme**: Bouton "Connect" reste en "Disconnected"

**Causes possibles**:
1. L'agent vocal s'est déconnecté après inactivité
2. LiveKit server redémarré
3. Token invalide

**Solution**:
```bash
# Redémarrer l'agent vocal
pkill -f "test_agent.py"
cd /opt/stacks/agents-playground
source .venv/bin/activate
LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=NtujbRjs7xfrS6ERkA6rXH-SyKfGXMCU_8FR0wexU-I VOICE_PERSONA=aria VOICE_LANGUAGE=fr OPENAI_API_KEY="sk-proj-..." python3 test_agent.py dev > /tmp/voice_agent.log 2>&1 &

# Rafraîchir le playground
# Dans le navigateur: Cmd+Shift+R (hard reload)
```

### 2. RPC Panel ne s'affiche pas

**Cause**: Le panneau n'apparaît que si:
- `connectionState === ConnectionState.Connected`
- `agent.isConnected === true`

**Solution**: Vérifier la connexion agent (voir section 1)

### 3. Erreur "No agent or room available"

**Cause**: `agent.internal.agentParticipant` est `undefined`

**Solution**: Attendre quelques secondes après "Connected" pour que l'agent rejoigne

---

## 📝 Next Steps

### Tests à faire

- [ ] Tester chacun des 10 RPC methods
- [ ] Vérifier le parsing des champs (text, select, number, comma-separated)
- [ ] Tester la gestion d'erreurs (champs manquants, valeurs invalides)
- [ ] Vérifier les logs côté agent
- [ ] Tester avec plusieurs clients simultanés
- [ ] Mesurer la latence RPC vs LLM function calling

### Améliorations futures

- [ ] Ajouter un historique des appels RPC
- [ ] Ajouter un bouton "Clear" pour réinitialiser le formulaire
- [ ] Sauvegarder les dernières valeurs utilisées (localStorage)
- [ ] Ajouter des exemples de payloads pré-remplis
- [ ] Implémenter une modale pour afficher les résultats volumineux
- [ ] Ajouter des indicateurs de latence (temps de réponse)

### Monitoring

- [ ] Créer un dashboard Grafana pour les métriques RPC
- [ ] Logger tous les appels RPC dans PostgreSQL (table `rpc_calls`)
- [ ] Ajouter des alertes pour les erreurs RPC fréquentes
- [ ] Mesurer le taux de succès par method

---

## 💰 Coûts

**OpenAI TTS** (temporaire, en attendant fix Chatterbox):
- tts-1: $15.00 / 1M caractères
- Estimation: ~$5-10/mois pour tests
- **Alternative**: Baseten hosting de Chatterbox (~$0.10/1K chars)

**Chatterbox local** (objectif):
- ResembleAI open-source (MIT license)
- 100% local, GPU-accelerated
- **Coût**: $0/mois ✅

---

## 📚 Documentation

### Liens utiles

- [LiveKit RPC Docs](https://docs.livekit.io/agents/server/rpc/)
- [LiveKit Agents SDK](https://docs.livekit.io/agents/)
- [Chatterbox TTS](https://github.com/resemble-ai/resemble-enhance)
- [Baseten TTS Integration](https://docs.livekit.io/agents/models/tts/plugins/baseten/)

### Issues GitHub

- [Open Source TTS Model Support #3711](https://github.com/livekit/livekit/issues/3711)

---

**Créé par**: Claude Sonnet 4.5
**Date**: 2026-01-03 03:10 AM
**Version**: 1.0
