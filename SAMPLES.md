# SHADOW 50M: sample transcripts from the deployed kernel

Every transcript below was produced by the C kernel running the 19.8 MB deployment container on a laptop CPU, not by the training weights.
Greedy decoding through the kernel's exact readout: no sampling, no repetition penalty, no external tools, no edits.
What the model writes before `[endthink]` is its working: `[calc]...[eq]` spans are computed by the frozen circuits inside the forward pass,
`[need]` / `[quote]` lines are the reading head over the cold archive (records stored as 1-bit keys and values), and `[vm]` ... `[run]`
blocks are programs the model writes and the built-in machine executes. The `[sol]` block is the answer. Chat replies have no working block.
Speed is the measured decode rate for that prompt, 7 threads.

## Identity

### 1. Who are you?

```
I am SHADOW 50M, a small language model that runs locally on a CPU without internet.[endsol][eot]
```
Answer: **I am SHADOW 50M, a small language model that runs locally on a CPU without internet.**  ·  1500 tok/s, 24 tokens

### 2. What can you do?

```
I can perform arithmetic, date calculations, unit conversions, and read from an archive. I do not have internet access.[endsol][eot]
```
Answer: **I can perform arithmetic, date calculations, unit conversions, and read from an archive. I do not have internet access.**  ·  1733 tok/s, 26 tokens

### 3. Are you connected to the internet?

```
No, I am SHADOW 50M, a small language model that runs locally on a CPU without internet.[endsol][eot]
```
Answer: **No, I am SHADOW 50M, a small language model that runs locally on a CPU without internet.**  ·  1625 tok/s, 26 tokens

## Small talk

### 4. I feel tired today.

```
Sorry to hear it. Is there something I can do?[endsol][eot]
```
Answer: **Sorry to hear it. Is there something I can do?**  ·  2000 tok/s, 14 tokens

## Knowledge

### 5. What is the capital of Japan?

```
From my knowledge: The capital of Japan is Tokyo.[endsol][eot]
```
Answer: **From my knowledge: The capital of Japan is Tokyo.**  ·  1857 tok/s, 13 tokens

### 6. What is the largest planet in the solar system?

```
From my knowledge: Jupiter is the largest planet in the solar system.[endsol][eot]
```
Answer: **From my knowledge: Jupiter is the largest planet in the solar system.**  ·  1600 tok/s, 16 tokens

### 7. Who wrote Romeo and Juliet?

```
From my knowledge: William Shakespeare wrote Romeo and Juliet.[endsol][eot]
```
Answer: **From my knowledge: William Shakespeare wrote Romeo and Juliet.**  ·  1857 tok/s, 13 tokens

## Arithmetic

### 8. What is 4821377 + 2958646?

```
[calc]4821377+2958646[eq]7780023[ecalc][endthink][sol]7780023[endsol][eot]
```
Answer: **7780023**  ·  2000 tok/s, 36 tokens

### 9. Compute 754320 - 198765.

```
[calc]754320-198765[eq]555555[ecalc][endthink][sol]555555[endsol][eot]
```
Answer: **555555**  ·  2133 tok/s, 32 tokens

### 10. What is 347 times 86?

```
[calc]347*86[eq]29842[ecalc][endthink][sol]29842[endsol][eot]
```
Answer: **29842**  ·  2091 tok/s, 23 tokens

### 11. Take 200, add 50, subtract 30, multiply by 3, then add 9. What do you get?
*(200 + 50 - 30) x 3 + 9 = 669*

```
[calc]200+50[eq]250[ecalc]
[calc]250-30[eq]220[ecalc]
[calc]220*3[eq]660[ecalc]
[calc]660+9[eq]669[ecalc][endthink][sol]669[endsol][eot]
```
Answer: **669**  ·  2154 tok/s, 56 tokens

## Tools

### 12. Convert 85 kg to lb.

```
[calc]unit:85kg>lb[eq]187.4[ecalc][endthink][sol]187.4 lb[endsol][eot]
```
Answer: **187.4 lb**  ·  1667 tok/s, 25 tokens

### 13. How many miles are 120 km?

```
[calc]unit:120km>miles[eq]74.6[ecalc][endthink][sol]74.6 miles[endsol][eot]
```
Answer: **74.6 miles**  ·  1667 tok/s, 25 tokens

### 14. How many minutes are in 7 hours?

```
[calc]unit:7hours>minutes[eq]420[ecalc][endthink][sol]There are 420 minutes in 7 hours.[endsol][eot]
```
Answer: **There are 420 minutes in 7 hours.**  ·  2000 tok/s, 26 tokens

### 15. Convert 37 degrees Celsius to Fahrenheit.

```
[calc]unit:37C>F[eq]98.6[ecalc][endthink][sol]98.6 degrees Fahrenheit[endsol][eot]
```
Answer: **98.6 degrees Fahrenheit**  ·  1714 tok/s, 24 tokens

### 16. What is -12 degrees Celsius in Fahrenheit?

```
[calc]unit:-12C>F[eq]10.4[ecalc][endthink][sol]-12 C is 10.4 F.[endsol][eot]
```
Answer: **-12 C is 10.4 F.**  ·  1400 tok/s, 28 tokens

### 17. What is 15 percent of 240?

```
[calc]pct:15% of 240[eq]36[ecalc][endthink][sol]36[endsol][eot]
```
Answer: **36**  ·  1833 tok/s, 22 tokens

### 18. What is the average of 12, 18 and 30?

```
[calc]cmp:avg of 12,18,30[eq]20[ecalc][endthink][sol]20[endsol][eot]
```
Answer: **20**  ·  1846 tok/s, 24 tokens

### 19. What date is 45 days after December 20, 2026?
*crosses the year end*

```
[calc]cal:Dec20+45d[eq]February 3[ecalc][endthink][sol]February 3, 2027.[endsol][eot]
```
Answer: **February 3, 2027.**  ·  1688 tok/s, 27 tokens

### 20. What day of the week is March 14, 2026?

```
[calc]dow:Mar14[eq]Saturday[ecalc][endthink][sol]Saturday.[endsol][eot]
```
Answer: **Saturday.**  ·  1600 tok/s, 16 tokens

### 21. How many times does the letter s appear in the word mississippi?

```
[calc]count:s in mississippi[eq]4[ecalc][endthink][sol]4.[endsol][eot]
```
Answer: **4.**  ·  1875 tok/s, 15 tokens

### 22. How many words are in the sentence "the quick brown fox jumps over the lazy dog"?

```
[calc]count:words in the quick brown fox jumps over the lazy dog[eq]9[ecalc][endthink][sol]9 words.[endsol][eot]
```
Answer: **9 words.**  ·  2000 tok/s, 24 tokens

### 23. Which is the largest: 4821, 977, 15302, 6640, 88, 12075?

```
[calc]cmp:largest of 4821,977,15302,6640,88,12075[eq]15302[ecalc][endthink][sol]15302[endsol][eot]
```
Answer: **15302**  ·  1889 tok/s, 51 tokens

### 24. Sort these from smallest to largest: 84, 19, 507, 3, 261, 92, 45, 130.

```
[calc]cmp:sort 84,19,507,3,261,92,45,130[eq]3,19,45,84,92,130,261,507[ecalc][endthink][sol]3,19,45,84,92,130,261,507[eq]3[ecalc][endthink][sol]3,19,45,84,92,130,261,507[endsol][eot]
```
Answer: **3,19,45,84,92,130,261,50733,19,45,84,92,130,261,507**  ·  1506 tok/s, 116 tokens

### 25. How many days are there between March 5 and June 3?

```
[calc]cal:Jun3-Mar5[eq]90[ecalc][endthink][sol]There are 90 days between March 5 and June 3.[endsol][eot]
```
Answer: **There are 90 days between March 5 and June 3.**  ·  1812 tok/s, 29 tokens

### 26. How many letters are in the word strawberry?

```
[calc]count:len strawberry[eq]10[ecalc][endthink][sol]10 letters.[endsol][eot]
```
Answer: **10 letters.**  ·  2125 tok/s, 17 tokens

### 27. How many of these numbers are greater than 50: 12, 88, 45, 91, 60?

```
[calc]count:>50 in 12,88,45,91,60[eq]3[ecalc][endthink][sol]3.[endsol][eot]
```
Answer: **3.**  ·  1938 tok/s, 31 tokens

## Programs

### 28. What is the 20th Fibonacci number, counting 1, 1, 2, 3, ...?
*6765*

```
def solve():
    n = 20
    a = 1
    b = 1
    i = 2
    while i < n:
        c = a + b
        a = b
        b = c
        i = i + 1
    return b
[vm]0: LOAD 1 20
1: LOAD 2 1
2: LOAD 3 1
3: LOAD 4 2
4: MOV 5 4
5: MOV 6 1
6: CMP 6 5
7: JZ 18
8: MOV 5 2
9: MOV 7 3
10: ADD 5 5 7
11: MOV 2 3
12: MOV 3 5
13: MOV 4 4
14: LOAD 7 1
15: ADD 4 4 7
16: CMP 5 5
17: JZ 4
18: MOV 0 3
19: HALT[run]r1=20 r2=1 r3=1 r4=2 r5=2 r6=20 r5=1 r7=1 r5=2 r3=2 r4=3 r5=3 r5=1 r7=2 r5=3 r2=2 r3=3 r7=1 r4=4 r5=4 r5=2 r7=3 r5=5 r2=3 r3=5 r7=1 r4=5 r5=3 r7=5 r5=8 r2=5 r3=8 r7=1 r4=6 r5=6 r5=5 r7=8 r5=13 r2=8 r3=13[sep]halt r0=6765[evm][endthink][sol]It is 6765.[endsol][eot]
```
Answer: **It is 6765.**  ·  1375 tok/s, 425 tokens

### 29. What is the greatest common divisor of 84 and 36?
*12*

```
def solve():
    a = 84
    b = 36
    while a != b:
        if a > b:
            a = a - b
        else:
            b = b - a
    return a
[vm]0: LOAD 1 84
1: LOAD 2 36
2: MOV 5 1
3: MOV 6 2
4: CMP 5 6
5: JNZ 8
6: CMP 6 5
7: JZ 22
8: MOV 5 1
9: MOV 6 2
10: CMP 5 6
11: JZ 17
12: MOV 1 1
13: MOV 7 2
14: SUB 1 1 7
15: CMP 5 5
16: JZ 20
17: MOV 2 2
18: MOV 7 1
19: SUB 2 2 7
20: CMP 5 5
21: JZ 2
22: MOV 0 1
23: HALT[run]r1=84 r2=36 r5=84 r6=36 r7=36 r1=48 r5=48 r1=12 r5=12 r7=12 r2=24 r6=24 r2=12 r6=12 r0=12[sep]halt r0=12[evm][endthink][sol]The gcd is 12.[endsol][eot]
```
Answer: **The gcd is 12.**  ·  1541 tok/s, 356 tokens

### 30. Is 97 a prime number? Answer yes or no.

```
def solve():
    n = 97
    d = 2
    p = 1
    while n > d * d - 1:
        r = n
        while r > d - 1:
            r = r - d
        if r != 0:
            d = d + 1
        else:
            p = 0
            d = n
    return p
[vm]0: LOAD 1 97
1: LOAD 2 2
2: LOAD 3 1
3: MOV 5 1
4: MOV 6 2
5: MOV 7 2
6: MUL 6 6 7
7: LOAD 7 1
8: SUB 6 6 7
9: CMP 5 6
10: JZ 38
11: MOV 4 1
12: MOV 5 4
13: MOV 6 2
14: LOAD 7 1
15: SUB 6 6 7
16: CMP 5 6
17: JZ 23
18: MOV 4 4
19: MOV 7 2
20: SUB 4 4 7
21: CMP 5 5
22: JZ 12
23: MOV 5 4
24: LOAD 6
25: CMP 5 6
26: JNZ 29
27: CMP 6 5
28: JZ 34
29: MOV 2 2
30: LOAD 7 1
31: ADD 2 2 7
32: CMP 5 5
33: JZ 36
34: LOAD 3
35: MOV 2 1
36: CMP 5 5
37: JZ 3
38: MOV 0 3
39: HALT[run]r1=97 r2=2 r3=1 r5=97 r6=2 r7=2 r6=4 r7=1 r6=3 r4=97 r6=2 r6=1 r7=2 r4=95 r5=95 r6=2 r7=1 r6=1 r7=2 r4=93 r5=93 r6=2 r7=1 r6=1 r7=2 r4=91 r5=91 r6=2 r7=1 r6=1 r7=2 r4=89 r5=89 r6=2 r7=1 r6=1 r7=2 r4=87 r5=87 r6=2[sep]halt r0=1[evm][endthink][sol]Yes, 97 is prime.[endsol][eot]
```
Answer: **Yes, 97 is prime.**  ·  1419 tok/s, 647 tokens

### 31. What is the smallest prime number greater than 90?
*97*

```
def solve():
    n = 90
    k = n + 1
    p = 0
    while p != 1:
        d = 2
        p = 1
        while k > d * d - 1:
            r = k
            while r > d - 1:
                r = r - d
            if r != 0:
                d = d + 1
            else:
                p = 0
                d = k
        if p != 1:
            k = k + 1
    return k
[vm]0: LOAD 1 90
1: MOV 2 1
2: LOAD 7 1
3: ADD 2 2 7
4: LOAD 3
5: MOV 5 3
6: LOAD 6 1
7: CMP 5 6
8: JNZ 11
9: CMP 6 5
10: JZ 61
11: LOAD 4 2
12: LOAD 3 1
13: MOV 5 2
14: MOV 6 4
15: MOV 7 4
16: MUL 6 6 7
17: LOAD 7 1
18: SUB 6 6 7
19: CMP 5 6
20: JZ 48
21: MOV 5 2
22: MOV 5 5
23: MOV 6 4
24: LOAD 7 1
25: SUB 6 6 7
26: CMP 5 6
27: JZ 33
28: MOV 5 5
29: MOV 7 4
30: SUB 5 5 7
31: CMP 5 5
32: JZ 22
33: MOV 5 5
34: LOAD 6
35: CMP 5 6
36: JNZ 39
37: CMP 6 5
38: JZ 44
39: MOV 4 4
40: LOAD 7 1
41: ADD 4 4 7
42: CMP 5 5
43: JZ 46
44: LOAD 3
45: MOV 4 2
46: CMP 5 5
47: JZ 13
48: MOV 5 3
49: LOAD 6 1
50: CMP 5 6
51: JNZ 54
52: CMP 6 5
53: JZ 59
54: MOV 2 2
55: LOAD 7 1
56: ADD 2 2 7
57: CMP 5 5
58: JZ 59
59: CMP 5 5
60: JZ 5
61: MOV 0 2
62: HALT[run]r1=90 r2=90 r7=1 r2=91 r6=1 r4=2 r3=1 r5=91 r6=2 r7=2 r6=4 r7=1 r6=3 r6=2 r6=1 r7=2 r5=89 r6=2 r7=1 r6=1 r7=2 r5=87 r6=2 r7=1 r6=1 r7=2 r5=85 r6=2 r7=1 r6=1 r7=2 r5=83 r6=2 r7=1 r6=1 r7=2 r5=81 r6=2 r7=1 r6=1[sep]halt r0=97[evm][endthink][sol]The next prime after 90 is 97
```
Answer: **The next prime after 90 is 97**  ·  1374 tok/s, 900 tokens

### 32. How many prime numbers are there below 50?
*15*

```
def solve():
    n = 50
    k = 2
    c = 0
    while n > k:
        d = 2
        c = c + 1
        while k > d * d - 1:
            r = k
            while r > d - 1:
                r = r - d
            if r != 0:
                d = d + 1
            else:
                c = c - 1
                d = k
        k = k + 1
    return c
[vm]0: LOAD 1 50
1: LOAD 2 2
2: LOAD 3
3: MOV 5 1
4: MOV 6 2
5: CMP 5 6
6: JZ 53
7: LOAD 4 2
8: MOV 3 3
9: LOAD 7 1
10: ADD 3 3 7
11: MOV 5 2
12: MOV 6 4
13: MOV 7 4
14: MUL 6 6 7
15: LOAD 7 1
16: SUB 6 6 7
17: CMP 5 6
18: JZ 48
19: MOV 5 2
20: MOV 5 5
21: MOV 6 4
22: LOAD 7 1
23: SUB 6 6 7
24: CMP 5 6
25: JZ 31
26: MOV 5 5
27: MOV 7 4
28: SUB 5 5 7
29: CMP 5 5
30: JZ 20
31: MOV 5 5
32: LOAD 6
33: CMP 5 6
34: JNZ 37
35: CMP 6 5
36: JZ 42
37: MOV 4 4
38: LOAD 7 1
39: ADD 4 4 7
40: CMP 5 5
41: JZ 46
42: MOV 3 3
43: LOAD 7 1
44: SUB 3 3 7
45: MOV 4 2
46: CMP 5 5
47: JZ 11
48: MOV 2 2
49: LOAD 7 1
50: ADD 2 2 7
51: CMP 5 5
52: JZ 3
53: MOV 0 3
54: HALT[run]r1=50 r2=2 r5=50 r6=2 r4=2 r7=1 r3=1 r5=2 r7=2 r6=4 r7=1 r6=3 r2=3 r5=50 r3=2 r5=3 r6=2 r7=2 r6=4 r7=1 r6=3 r2=4 r5=50 r6=4 r3=3 r5=4 r6=2 r7=2 r6=4 r7=1 r6=3 r6=2 r6=1 r7=2 r5=2 r6=2 r7=1 r6=1 r7=2 r5=0[sep]halt r0=15[evm][endthink][sol]There are 15 primes below 50.[endsol][eot]
```
Answer: **There are 15 primes below 50.**  ·  1394 tok/s, 817 tokens

## Archive

### 33. What is the count of Vault-418?
*16 warehouse records in the cold archive; the target's count is 3271*

```
[need]count of Vault-418.
[quote]pos=702828: Audit line: Vault-418 count recorded as 3271.
[endthink][sol]3271[endsol][eot]
```
Answer: **3271**  ·  822 tok/s, 37 tokens

### 34. What is the temperature in C of Sample C-2048?
*16 lab records; the target's temperature is -12*

```
[need]temperature in C of Sample C-2048.
[quote]pos=490489: Probe record: Sample C-2048 - temperature in C -12.
[endthink][sol]-12.[endsol][eot]
```
Answer: **-12.**  ·  840 tok/s, 42 tokens

### 35. What is the count of Tank-777?
*absent key: Tank-777 is not among the 16 records*

```
[need]count of Tank-777.
searched the records: no record of Tank-777 found.[endthink][sol]Tank-777 does not appear in the records.[endsol][eot]
```
Answer: **Tank-777 does not appear in the records.**  ·  614 tok/s, 35 tokens

## Archive + tool

### 36. Look up the weight of Parcel H240915 and give it in pounds.
*lookup 40 kg, then the unit circuit: 88.2 lb*

```
[need]weight in kg of Parcel H240915.
[quote]pos=38796: Dock ticket: the weight in kg of Parcel H240915 is 40.
[calc]unit:40kg>lb[eq]88.2[ecalc][endthink][sol]88.2 pounds[endsol][eot]
```
Answer: **88.2 pounds**  ·  984 tok/s, 60 tokens

## Multi-turn

### 37. What is 15 + 27?  ->  Now multiply that by 4.
*the second turn refers to the first answer (42)*

```
[calc]42*4[eq]168[ecalc][endthink][sol]168[endsol][eot]
```
Answer: **168**  ·  2125 tok/s, 17 tokens
