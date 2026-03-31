import asyncio
from arkitect.core.component.context.context import Context

async def main():
    prompt = "una donna vestita di nero cammina sotto il sole di mezzogiorno, la camera si muove con lei"
    print("🎬 Avvio generazione con modello Doubao (test connessione Ark)...")

    try:
        # Usa un modello attivo per testare la connessione
        ctx = Context(model="doubao-1.5-pro-32k-250115")
        await ctx.init()

        # Invia il prompt al modello
        response = await ctx.completions.create(
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )

        print("✅ Risposta ricevuta:")
        print(response)

    except Exception as e:
        print("❌ Errore:", e)

if __name__ == "__main__":
    asyncio.run(main())
