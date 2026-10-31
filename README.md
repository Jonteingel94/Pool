Quant Pool Engine 3.0
Streamlit-app för att analysera 8- och 13-matchers poolkuponger.
Starta
python -m pip install -r requirements.txt
streamlit run App.py
Strategier
Högsta träffchans (A): de exakt K mest sannolika raderna under antagandet att matcher är oberoende. Detta maximerar modellens chans till alla rätt för K unika rader.
Balanserad (B): kandidatbaserad streckvärdesheuristik med minst 1 - balance av A:s modellerade sannolikhetsmassa. Standard balance=0.30 innebär minst 70 %.
Mer streckvärde (C): kandidatbaserad streckvärdesheuristik med minst 35 % av A:s sannolikhetsmassa.
Strategierna B och C maximerar inte verifierad ekonomisk förväntan. Streckandelar kan användas som popularitetsproxy, men är inte en utdelningsmodell.
Backtesting
Ladda upp en CSV med en rad per match och kolumnerna:
draw,match,p1,px,p2,s1,sx,s2,result
draw: omgångs-ID; match: matchnummer (1–8 eller 1–13).
p1,px,p2: förhandsberäknade sannolikheter som summerar till 1 per match.
s1,sx,s2: förhandsregistrerade streckandelar som summerar till 1 per match.
result: faktiskt utfall 1, X eller 2.
Använd inte slutodds eller slutstreck om dessa inte var tillgängliga vid det tidssnitt strategin ska efterlikna. Annars uppstår informationsläckage. Backtestet visar högsta antal rätt och antal fullträffar per strategi/omgång, men inte vinst i kronor. Verkliga historiska omgångar och utdelningsdata ingår inte i detta paket.
Export
CSV och TXT med E-rader stöds. TXT-formatet är byggt för jämförelse med äldre filer och är inte verifierat som inlämningsformat hos Svenska Spel. Ingen inlämning sker automatiskt.
Begränsningar
Sannolikheterna från odds/streck kan vara felkalibrerade. Oberoende mellan matcher är ett antagande. Backtesting på historiska data krävs för att utvärdera modellerna. Ingen vinst eller positiv förväntad avkastning garanteras.
Tester
python -m pytest -q