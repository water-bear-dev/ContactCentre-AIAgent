# Comprehensive Implementation Plan: Asterisk + PersonaPlex + Real Calls + Voice Cloning + Web UI

## Executive Summary
This document outlines the end-to-end plan to transform the existing text-based multi-tenant AI receptionist into a production-grade voice contact centre agent. 

### The Logical First Step
**Phase 1: Local Real-Time Voice Streaming Pipeline (Mock/Web Audio)**
Before configuring Asterisk, SIP trunks, or phone carriers, we must validate the low-latency audio loop locally:
$$\text{Microphone Input} \rightarrow \text{Streaming STT} \rightarrow \text{PersonaPlex LLM Orchestrator} \rightarrow \text{Voice Cloning TTS} \rightarrow \text{Speaker Output}$$
Once this sub-second loop works with barge-in/interruption over WebSockets, plugging in Asterisk is simply swapping the audio stream source from a browser mic to a telephony channel.

---

## Architecture Blueprint

```
                      [ Real Caller (PSTN / Mobile) ]
                                     │
                                     ▼
                      [ SIP Provider (Twilio / Telnyx) ]
                                     │ (SIP / RTP)
                                     ▼
                      [ Asterisk PBX (Docker / VPS) ]
                                     │ (AudioSocket TCP / ARI)
                                     ▼
       ┌────────────────────────────────────────────────────────┐
       │                Telephony Media Bridge                  │
       │    - Resampling (8kHz G.711 <-> 16/24kHz High-Fi)      │
       │    - Silero VAD (Voice Activity Detection & Barge-in)  │
       └──────────────┬───────────────────────────▲─────────────┘
                      │ Audio Chunks              │ Cloned Audio Stream
                      ▼                           │
              [ Streaming STT ]           [ Voice Cloning TTS ]
             (Deepgram Nova-2)            (Cartesia / ElevenLabs)
                      │                           ▲
                      │ Transcripts               │ Generated Text Stream
                      ▼                           │
       ┌──────────────────────────────────────────┴─────────────┐
       │               PersonaPlex Orchestrator                 │
       │    - Multi-tenant prompt & persona injection           │
       │    - Function calling (booking, transfer, CRM lookup)  │
       │    - Conversation state & turn taking                  │
       └──────────────────────────────┬─────────────────────────┘
                                      │ Telemetry & Events
                                      ▼
                        [ Modern Web UI Dashboard ]
                        - Live call inspector & waveform
                        - Real-time transcript stream
                        - Voice clone sample upload & preview
                        - Tenant & persona configuration
```

---

## Detailed Phase Breakdown

### Phase 1: Real-Time Audio Streaming & Voice Cloning Engine
*Goal: Achieve full bidirectional audio dialogue with voice cloning and barge-in locally.*

1. **Streaming STT Integration**:
   - Integrate streaming Speech-to-Text (Deepgram Nova-2 WebSockets or streaming Whisper).
   - Low-latency partial transcript handling with endpointing.
2. **Streaming Voice Cloning TTS**:
   - Integrate low-latency cloned TTS provider (Cartesia Sonic or ElevenLabs Turbo v2.5 / Conversational AI).
   - Audio buffer streaming with chunked byte delivery.
3. **Barge-In / Interruption Controller**:
   - Integrate Silero VAD to detect caller speech while agent is speaking.
   - Instantly issue cancel/flush commands to stop audio playback when the user interrupts.
4. **PersonaPlex Pipeline Glue**:
   - Connect audio pipeline to existing `app/receptionist.py` tenant prompts and tool execution.

---

### Phase 2: Asterisk PBX & AudioSocket Telephony Bridge
*Goal: Enable Asterisk to stream call audio directly into the AI pipeline.*

1. **Asterisk Environment Setup**:
   - Dockerized Asterisk 20+ setup with `res_http_websocket`, `app_audiosocket`, and ARI enabled.
   - Dialplan (`extensions.conf`) configured to route inbound calls straight to the AudioSocket bridge.
2. **Bidirectional Telephony Media Bridge**:
   - Implement `AudioSocket` TCP server in Python.
   - Format conversion: Telephony 8kHz (or 16kHz SLIN) $\leftrightarrow$ STT/TTS 16kHz/24kHz PCM linear format.
3. **Call Control & Signaling**:
   - Handle Call Start (UUID / Caller ID capture), Hangup, and DTMF detection.
   - Call transfer support (`Dial` or ARI redirect to a human queue when escalated).

---

### Phase 3: Real Inbound & Outbound Calling (PSTN / SIP)
*Goal: Receive real phone calls from mobile phones/landlines and dial out.*

1. **SIP Trunk Configuration**:
   - Configure SIP peer (PJSIP) in Asterisk for carrier (Telnyx, Twilio Elastic SIP, or SignalWire).
2. **Inbound Routing & Tenant Mapping**:
   - Map incoming DID numbers (e.g. `+1-xxx-xxx-xxxx`) to specific tenant/business personas in PersonaPlex.
3. **Latency & Jitter Tuning**:
   - Optimize RTP buffer sizes, network jitter handling, and packet loss concealment.
   - Measure and enforce end-to-end response latency under 800ms.

---

### Phase 4: Next-Gen Web UI & Call Operations Dashboard
*Goal: Provide a premium interface for monitoring calls, managing personas, and testing voice clones.*

1. **Live Call Monitoring**:
   - Active call cards with caller ID, duration, and status indicators.
   - Live real-time transcription feed over WebSocket.
   - Audio visualizer (input and output waveforms).
2. **Voice Cloning Studio**:
   - Audio sample file upload (MP3/WAV) or in-browser voice recording.
   - Preview synthesized cloned audio before assigning to an agent persona.
3. **PersonaPlex Management**:
   - Edit business knowledge, system prompts, operational hours, and tool configurations per tenant.
4. **Call Logs & Recordings**:
   - Audio playback of past calls with synchronized transcript inspection and tool execution logs.

---

## What We Need From You (Inputs & Credentials)

To advance through each phase, here is what is needed:

| Phase | Item Needed from You | Notes |
| :--- | :--- | :--- |
| **Phase 1** | **LLM API Key** (OpenAI / Anthropic / Groq) | For conversation intelligence and function calling. |
| **Phase 1** | **TTS / Voice Cloning Key** (Cartesia or ElevenLabs) | Cartesia is recommended for ultra-low latency (<100ms); ElevenLabs for fidelity. |
| **Phase 1** | **STT Key** (Deepgram recommended) | Deepgram Nova-2 is the industry standard for telephony streaming STT. |
| **Phase 2 & 3** | **SIP Trunk Account & Phone Number** | Twilio, Telnyx, or VoIP.ms credentials with at least 1 DID number. |
| **Phase 2 & 3** | **Hosting / Deployment Target** | Local Docker (with ngrok/port forwarding) or a cloud VPS (DigitalOcean/AWS EC2) with a public IP for SIP/RTP ports. |
| **Phase 4** | **Target Brand / Design Preferences** | Preferred color palette, tenant details, and specific operational tools needed. |

---

## Action Plan & Immediate Next Step

1. **Immediate Step**: Build the **Phase 1 Local Voice Streaming Prototype** (browser mic $\rightarrow$ STT $\rightarrow$ PersonaPlex $\rightarrow$ Cloned TTS) using FastAPI WebSockets.
2. Once Phase 1 is validated locally with your API keys, we spin up the **Dockerized Asterisk PBX** and connect the AudioSocket bridge.
