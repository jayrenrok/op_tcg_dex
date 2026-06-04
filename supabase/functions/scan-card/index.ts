import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// Generate JWT for Google Service Account auth
async function getAccessToken(serviceAccount: any): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const payload = {
    iss: serviceAccount.client_email,
    scope: "https://www.googleapis.com/auth/cloud-platform",
    aud: serviceAccount.token_uri,
    exp: now + 3600,
    iat: now,
  };

  const encode = (obj: any) =>
    btoa(JSON.stringify(obj)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");

  const headerB64 = encode(header);
  const payloadB64 = encode(payload);
  const signingInput = `${headerB64}.${payloadB64}`;

  // Import private key
  const pemKey = serviceAccount.private_key
    .replace("-----BEGIN PRIVATE KEY-----", "")
    .replace("-----END PRIVATE KEY-----", "")
    .replace(/\n/g, "");

  const keyData = Uint8Array.from(atob(pemKey), (c) => c.charCodeAt(0));
  const cryptoKey = await crypto.subtle.importKey(
    "pkcs8",
    keyData,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const encoder = new TextEncoder();
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    cryptoKey,
    encoder.encode(signingInput)
  );

  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(signature)))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");

  const jwt = `${signingInput}.${sigB64}`;

  // Exchange JWT for access token
  const tokenRes = await fetch(serviceAccount.token_uri, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}`,
  });

  const tokenData = await tokenRes.json();
  if (!tokenData.access_token) {
    throw new Error(`Token error: ${JSON.stringify(tokenData)}`);
  }
  return tokenData.access_token;
}

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { image_base64, mime_type = "image/jpeg" } = await req.json();

    if (!image_base64) {
      return new Response(JSON.stringify({ error: "No image provided" }), {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // Load service account from env
    const serviceAccount = JSON.parse(Deno.env.get("GOOGLE_SERVICE_ACCOUNT")!);
    const projectId = serviceAccount.project_id;
    const accessToken = await getAccessToken(serviceAccount);

    const prompt = `You are an expert One Piece Trading Card Game identifier. Analyze this card image and extract the following information. Return ONLY a valid JSON object with no markdown, no explanation, just raw JSON.

{
  "id": "card set ID like OP09-118 or ST01-001",
  "name": "English card name",
  "name_jp": "Japanese card name if visible",
  "type": "CHARACTER or LEADER or EVENT or STAGE",
  "color": "Red/Blue/Green/Yellow/Purple/Black/Multi",
  "rarity": "C/UC/R/SR/SEC/L or with variant like SEC (Alternate Art)",
  "cost": null,
  "power": null,
  "counter": null,
  "ability_summary": "brief summary of the card effect in English",
  "confidence": "high/medium/low",
  "notes": "any special variants like Parallel, Alternate Art, Foil, etc"
}

If you cannot read the card ID clearly, make your best guess based on the artwork and text visible. Always include confidence level.`;

    // Call Vertex AI Gemini
    const vertexUrl = `https://us-central1-aiplatform.googleapis.com/v1/projects/${projectId}/locations/us-central1/publishers/google/models/gemini-1.5-flash:generateContent`;

    const vertexRes = await fetch(vertexUrl, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        contents: [{
          role: "user",
          parts: [
            { text: prompt },
            { inline_data: { mime_type, data: image_base64 } },
          ],
        }],
        generationConfig: { temperature: 0.1, maxOutputTokens: 1024 },
      }),
    });

    const vertexData = await vertexRes.json();

    if (!vertexRes.ok) {
      throw new Error(vertexData.error?.message || "Vertex AI error");
    }

    const rawText = vertexData.candidates?.[0]?.content?.parts?.[0]?.text || "";
    const clean = rawText.replace(/```json|```/g, "").trim();
    const card = JSON.parse(clean);

    return new Response(JSON.stringify({ success: true, card }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });

  } catch (err) {
    return new Response(JSON.stringify({ success: false, error: err.message }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
