"""The twenty README questions through Supra-50M-Reasoning, greedy, its own prompt format.
Records are given in the prompt (it has no memory of its own)."""
import json, sys, time, re
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from huggingface_hub import snapshot_download
S = snapshot_download("SupraLabs/Supra-50M-Reasoning")
dev = "cuda"
tok = AutoTokenizer.from_pretrained(S)
m = AutoModelForCausalLM.from_pretrained(S, dtype=torch.float32).to(dev).eval()
SYS = ("Your role as an assistant involves thoroughly exploring questions through a systematic long thinking "
       "process before providing the final precise and accurate solutions.")
RECORDS = ("Records:\nPatient P-204 condition: asthma.\nPatient P-204 allergy: penicillin.\n"
           "Patient R-118 condition: hypertension.\nPatient R-118 allergy: none recorded.\n"
           "Sample K-77 weight in kg: 12.\nSample K-77 temperature in C: 21.\n"
           "Parcel M-3310 weight in kg: 40.\nVault-418 count: 3271.\n\n")
Q = [
 "Who are you?", "What is the capital of Japan?", "Who wrote Romeo and Juliet?",
 "Tell me a short joke about computers.", "Write a short poem about rain.",
 "I have 3 books and I bought 5 more. How many books do I have now?",
 "A train had 48 passengers and 19 got off. How many passengers are left?",
 "There are 7 boxes with 12 eggs in each box. How many eggs is that in total?",
 "I split 96 apples equally into 8 bags. How many apples are in each bag?",
 "My bill is 240 dollars. What is 15 percent of that?",
 "What date is 45 days after December 20, 2026?",
 "My exam is on March 14, 2026. What day of the week is that?",
 "My suitcase weighs 23 kg. What is that in pounds?",
 "How many times does the letter s appear in the word mississippi?",
 "Sort these from smallest to largest: 84, 19, 507, 3, 261.",
 "Take 200, add 50, subtract 30, multiply by 3, then add 9. What do you get?",
 RECORDS + "What is the condition of Patient P-204?",
 RECORDS + "What is the allergy of Patient P-204?",
 RECORDS + "Look up the weight in kg of Sample K-77 and give it in pounds.",
 RECORDS + "What is the condition of Patient Z-999?",
]
out = []
for i, q in enumerate(Q, 1):
    p = f"[SYSTEM]: {SYS}\n\n[USER]: {q}\n\n[ASSISTANT]: <|begin_of_thought|>\n"
    ids = tok(p, return_tensors="pt").input_ids.to(dev)
    t = time.time()
    with torch.no_grad():
        if "--sample" in sys.argv:
            torch.manual_seed(0)
            o = m.generate(ids, max_new_tokens=600, do_sample=True, temperature=0.3, top_k=25, top_p=0.8,
                           repetition_penalty=1.3, pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)
        else:
            o = m.generate(ids, max_new_tokens=600, do_sample=False, repetition_penalty=1.3,
                           pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)
    txt = tok.decode(o[0][ids.shape[1]:], skip_special_tokens=False)
    n = o.shape[1] - ids.shape[1]
    sol = re.search(r"<\|begin_of_solution\|>(.*?)(<\|end_of_solution\|>|$)", txt, re.S)
    sol = sol.group(1).strip() if sol else "(no solution block within 600 tokens)"
    out.append(dict(i=i, q=q.replace(RECORDS, "[records] "), tokens=n, secs=round(time.time() - t, 1), solution=sol, raw=txt))
    print(i, q.replace(RECORDS, "[records] ")[:70], "|", n, "tok |", sol[:300].replace("\n", " "), flush=True)
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "gen_supra.json", "w"), indent=1)
