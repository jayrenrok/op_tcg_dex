import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { GoogleGenAI } from "https://esm.sh/@google/genai";

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

    const apiKey = Deno.env.get("GEMINI_API_KEY")!;
    const ai = new GoogleGenAI({ apiKey });

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

    const response = await ai.models.generateContent({
      model: "gemini-1.5-flash",
      contents: [{
        role: "user",
        parts: [
          { text: prompt },
          { inlineData: { mimeType: mime_type, data: image_base64 } },
        ],
      }],
    });

    const rawText = response.text ?? "";
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
