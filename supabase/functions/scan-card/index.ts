import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

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

    const apiKey = Deno.env.get("GEMINI_API_KEY");
    if (!apiKey) {
      return new Response(JSON.stringify({ error: "Missing GEMINI_API_KEY" }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // Strip base64 prefix if present
    const cleanBase64 = image_base64.includes(",")
      ? image_base64.split(",")[1]
      : image_base64;

    const prompt = `You are an expert One Piece Trading Card Game identifier. Analyze this card image and extract the following information. Return ONLY a valid JSON object with no markdown, no explanation, just raw JSON.
{"id":"card set ID like OP09-118","name":"English card name","name_jp":"Japanese name if visible","type":"CHARACTER or LEADER or EVENT or STAGE","color":"Red/Blue/Green/Yellow/Purple/Black/Multi","rarity":"C/UC/R/SR/SEC/L","cost":null,"power":null,"ability_summary":"brief effect summary","confidence":"high/medium/low","notes":"special variants like Alternate Art, Parallel, Foil"}
Make your best guess if unsure. Always include confidence.`;

    const url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent";

    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": apiKey,
      },
      body: JSON.stringify({
        contents: [{
          parts: [
            { text: prompt },
            { inline_data: { mime_type, data: cleanBase64 } },
          ],
        }],
        generationConfig: { temperature: 0.1, maxOutputTokens: 512 },
      }),
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`Gemini API error: ${errorText}`);
    }

    const data = await res.json();
    const rawText = data.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
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
