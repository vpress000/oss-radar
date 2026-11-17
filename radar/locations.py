"""Turn the free-text location on a GitHub profile into a directory section.

People write anything here: "SF", "Gurnee, IL", "Tokyo - Japan", "Earth". The text is split
into comma-separated parts. A place name may be followed by a state, province or country that
settles which place is meant ("Paris, TX" is in Texas, "Paris, France" is not). When one
profile names several places ("Berlin / SF"), an SF Bay Area place wins, then a US place,
because those are the sections this directory highlights.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import NamedTuple

BAY = "sf-bay-area"
US = "rest-of-us"
OUTSIDE = "outside-us"
UNKNOWN = "location-unknown"
USA = "United States"


@dataclass(frozen=True)
class Place:
    section: str
    state: str | None = None    # two-letter US state code, when known
    country: str | None = None  # "United States" or another country, when known


UNKNOWN_PLACE = Place(UNKNOWN)

# --- United States ---------------------------------------------------------------------------

US_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "dc": "district of columbia",
    "fl": "florida", "ga": "georgia", "hi": "hawaii", "id": "idaho", "il": "illinois",
    "in": "indiana", "ia": "iowa", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "me": "maine", "md": "maryland", "ma": "massachusetts", "mi": "michigan",
    "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey",
    "nm": "new mexico", "ny": "new york", "nc": "north carolina", "nd": "north dakota",
    "oh": "ohio", "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania",
    "ri": "rhode island", "sc": "south carolina", "sd": "south dakota", "tn": "tennessee",
    "tx": "texas", "ut": "utah", "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming", "pr": "puerto rico",
}

US_NAMES = (
    "united states", "united states of america", "usa", "us", "america", "the us", "the usa",
    "the united states", "estados unidos", "etats-unis",
)

US_CITIES = {
    "new york city": "NY", "nyc": "NY", "manhattan": "NY", "brooklyn": "NY", "queens": "NY",
    "bronx": "NY", "staten island": "NY", "long island": "NY", "buffalo": "NY",
    "syracuse": "NY", "ithaca": "NY", "white plains": "NY",
    "los angeles": "CA", "santa monica": "CA", "pasadena": "CA", "burbank": "CA",
    "irvine": "CA", "san diego": "CA", "sacramento": "CA", "santa barbara": "CA",
    "culver city": "CA", "long beach": "CA", "anaheim": "CA", "riverside": "CA",
    "fresno": "CA", "bakersfield": "CA", "la jolla": "CA", "carlsbad": "CA",
    "el segundo": "CA", "playa vista": "CA", "marina del rey": "CA", "hollywood": "CA",
    "malibu": "CA", "newport beach": "CA", "costa mesa": "CA", "torrance": "CA",
    "thousand oaks": "CA", "san luis obispo": "CA", "monterey": "CA", "santa cruz": "CA",
    "seattle": "WA", "redmond": "WA", "kirkland": "WA", "tacoma": "WA", "spokane": "WA",
    "olympia": "WA", "bothell": "WA", "issaquah": "WA", "renton": "WA",
    "eugene": "OR", "beaverton": "OR", "hillsboro": "OR", "corvallis": "OR",
    "boston": "MA", "somerville": "MA", "waltham": "MA", "brookline": "MA", "amherst": "MA",
    "providence": "RI", "hartford": "CT", "new haven": "CT", "stamford": "CT",
    "chicago": "IL", "evanston": "IL", "naperville": "IL", "champaign": "IL", "urbana": "IL",
    "austin": "TX", "dallas": "TX", "houston": "TX", "san antonio": "TX", "fort worth": "TX",
    "plano": "TX", "irving": "TX", "frisco": "TX", "el paso": "TX", "round rock": "TX",
    "denver": "CO", "boulder": "CO", "colorado springs": "CO", "fort collins": "CO",
    "atlanta": "GA", "savannah": "GA",
    "miami": "FL", "tampa": "FL", "tampa bay": "FL", "orlando": "FL", "jacksonville": "FL",
    "tallahassee": "FL", "gainesville": "FL", "fort lauderdale": "FL", "boca raton": "FL",
    "philadelphia": "PA", "philly": "PA", "pittsburgh": "PA", "harrisburg": "PA",
    "washington dc": "DC", "dc": "DC",
    "baltimore": "MD", "bethesda": "MD", "rockville": "MD", "silver spring": "MD",
    "annapolis": "MD",
    "reston": "VA", "mclean": "VA", "fairfax": "VA", "herndon": "VA", "virginia beach": "VA",
    "charlottesville": "VA", "blacksburg": "VA",
    "raleigh": "NC", "chapel hill": "NC", "charlotte": "NC", "research triangle": "NC",
    "cary": "NC", "asheville": "NC",
    "nashville": "TN", "memphis": "TN", "knoxville": "TN", "chattanooga": "TN",
    "minneapolis": "MN", "saint paul": "MN",
    "detroit": "MI", "ann arbor": "MI", "grand rapids": "MI", "lansing": "MI",
    "cleveland": "OH", "cincinnati": "OH", "dayton": "OH",
    "indianapolis": "IN", "west lafayette": "IN",
    "milwaukee": "WI", "madison": "WI",
    "saint louis": "MO",
    "new orleans": "LA", "baton rouge": "LA",
    "las vegas": "NV", "reno": "NV",
    "phoenix": "AZ", "tempe": "AZ", "scottsdale": "AZ", "tucson": "AZ",
    "salt lake city": "UT", "provo": "UT", "lehi": "UT", "ogden": "UT", "park city": "UT",
    "albuquerque": "NM", "santa fe": "NM",
    "boise": "ID", "honolulu": "HI", "anchorage": "AK", "omaha": "NE",
    "des moines": "IA", "iowa city": "IA", "oklahoma city": "OK", "tulsa": "OK",
    "louisville": "KY", "little rock": "AR", "huntsville": "AL", "erie": "PA",
    "princeton": "NJ", "hoboken": "NJ", "jersey city": "NJ", "san juan": "PR",
    "silicon alley": "NY", "socal": "CA", "norcal": "CA", "southern california": "CA",
    "northern california": "CA",
    # Regions and names shared by several US states: still the US, just no state
    "pacific northwest": None, "pnw": None, "midwest": None, "new england": None,
    "east coast": None, "west coast": None,
    "portland": None, "columbus": None, "springfield": None, "kansas city": None,
    "arlington": None, "newark": None, "albany": None, "concord": None, "danville": None,
    "belmont": None, "saratoga": None, "union city": None, "lafayette": None,
    "pleasant hill": None, "glendale": None, "rochester": None, "bellevue": None,
}

# --- SF Bay Area -----------------------------------------------------------------------------

BAY_PLACES = (
    "san francisco", "sf", "sfo", "san fran", "sf bay area", "san francisco bay area",
    "bay area", "the bay area", "silicon valley", "east bay", "oakland", "berkeley",
    "emeryville", "el cerrito", "san leandro", "hayward", "fremont", "milpitas", "san jose",
    "santa clara", "sunnyvale", "mountain view", "palo alto", "east palo alto", "menlo park",
    "atherton", "portola valley", "redwood city", "redwood shores", "san carlos", "san mateo",
    "foster city", "burlingame", "millbrae", "san bruno", "south san francisco", "daly city",
    "pacifica", "half moon bay", "los altos", "los altos hills", "cupertino", "los gatos",
    "morgan hill", "gilroy", "walnut creek", "orinda", "moraga", "pleasanton", "livermore",
    "san ramon", "castro valley", "san rafael", "mill valley", "sausalito", "novato",
    "larkspur", "tiburon", "corte madera", "vallejo", "benicia", "stanford", "alameda",
    "petaluma", "napa", "sonoma",
)

# Bay Area names that also exist elsewhere: Bay Area only with a California qualifier
# ("Dublin, CA" vs "Dublin, Ireland").
BAY_IF_CALIFORNIA = {
    "richmond", "albany", "newark", "concord", "danville", "belmont", "saratoga",
    "union city", "lafayette", "campbell", "martinez", "pleasant hill", "dublin", "woodside",
    "santa rosa", "san pablo", "brisbane",
}

# Names that can't be placed without a qualifier ("Cambridge" alone: UK or Massachusetts?)
AMBIGUOUS = (
    "richmond", "cambridge", "birmingham", "oxford", "bristol", "athens",
    "alexandria", "victoria", "waterloo", "hamilton", "kingston", "cali", "saint petersburg",
    "aurora", "jackson", "durham", "worcester", "plymouth", "lancaster", "salem", "lexington",
    "charleston", "burlington", "wilmington", "bloomington", "campbell", "martinez",
    "woodside", "santa rosa", "san pablo",
)

# --- Canada ----------------------------------------------------------------------------------

CA_PROVINCES = {
    "ontario": "on", "quebec": "qc", "british columbia": "bc", "alberta": "ab",
    "manitoba": "mb", "saskatchewan": "sk", "nova scotia": "ns", "new brunswick": "nb",
    "newfoundland": "nl", "newfoundland and labrador": "nl", "prince edward island": "pe",
    "yukon": "yt", "northwest territories": "nt", "nunavut": "nu",
}
CA_PROVINCE_CODES = set(CA_PROVINCES.values())

# --- Rest of the world -----------------------------------------------------------------------

COUNTRIES = {
    "United Kingdom": "united kingdom|uk|great britain|britain|england|scotland|wales|northern ireland",
    "Ireland": "ireland|eire",
    "France": "france",
    "Germany": "germany|deutschland",
    "Netherlands": "netherlands|the netherlands|holland|nederland",
    "Belgium": "belgium|belgique|belgie",
    "Luxembourg": "luxembourg",
    "Liechtenstein": "liechtenstein",
    "Switzerland": "switzerland|schweiz|suisse|svizzera",
    "Austria": "austria|osterreich",
    "Italy": "italy|italia",
    "Spain": "spain|espana",
    "Portugal": "portugal",
    "Denmark": "denmark|danmark",
    "Norway": "norway|norge",
    "Sweden": "sweden|sverige",
    "Finland": "finland|suomi",
    "Iceland": "iceland",
    "Poland": "poland|polska",
    "Czechia": "czech republic|czechia|cesko",
    "Slovakia": "slovakia",
    "Hungary": "hungary|magyarorszag",
    "Romania": "romania",
    "Bulgaria": "bulgaria",
    "Greece": "greece",
    "Croatia": "croatia|hrvatska",
    "Serbia": "serbia|srbija",
    "Slovenia": "slovenia",
    "Bosnia and Herzegovina": "bosnia|bosnia and herzegovina",
    "Montenegro": "montenegro",
    "Albania": "albania",
    "North Macedonia": "north macedonia|macedonia",
    "Kosovo": "kosovo",
    "Moldova": "moldova",
    "Estonia": "estonia|eesti",
    "Latvia": "latvia",
    "Lithuania": "lithuania",
    "Belarus": "belarus",
    "Ukraine": "ukraine",
    "Russia": "russia|russian federation",
    "Cyprus": "cyprus",
    "Malta": "malta",
    "Turkey": "turkey|turkiye",
    "Israel": "israel",
    "Palestine": "palestine",
    "Lebanon": "lebanon",
    "Jordan": "jordan",
    "Syria": "syria",
    "Iraq": "iraq",
    "Iran": "iran",
    "Saudi Arabia": "saudi arabia|ksa",
    "United Arab Emirates": "united arab emirates|uae",
    "Qatar": "qatar",
    "Bahrain": "bahrain",
    "Kuwait": "kuwait",
    "Oman": "oman",
    "Yemen": "yemen",
    "India": "india|bharat",
    "Pakistan": "pakistan",
    "Bangladesh": "bangladesh",
    "Sri Lanka": "sri lanka",
    "Nepal": "nepal",
    "Bhutan": "bhutan",
    "Afghanistan": "afghanistan",
    "China": "china|prc|peoples republic of china",
    "Hong Kong": "hong kong|hongkong",
    "Macau": "macau|macao",
    "Taiwan": "taiwan",
    "Japan": "japan|nippon",
    "South Korea": "south korea|korea|republic of korea",
    "North Korea": "north korea",
    "Mongolia": "mongolia",
    "Singapore": "singapore",
    "Malaysia": "malaysia",
    "Indonesia": "indonesia",
    "Thailand": "thailand",
    "Vietnam": "vietnam|viet nam",
    "Philippines": "philippines",
    "Cambodia": "cambodia",
    "Laos": "laos",
    "Myanmar": "myanmar|burma",
    "Kazakhstan": "kazakhstan",
    "Uzbekistan": "uzbekistan",
    "Kyrgyzstan": "kyrgyzstan",
    "Azerbaijan": "azerbaijan",
    "Armenia": "armenia",
    "Georgia": "sakartvelo",  # plain "Georgia" could be the US state; see classify()
    "Canada": "canada",
    "Mexico": "mexico",
    "Guatemala": "guatemala",
    "Honduras": "honduras",
    "El Salvador": "el salvador",
    "Nicaragua": "nicaragua",
    "Costa Rica": "costa rica",
    "Panama": "panama",
    "Cuba": "cuba",
    "Dominican Republic": "dominican republic",
    "Jamaica": "jamaica",
    "Colombia": "colombia",
    "Venezuela": "venezuela",
    "Ecuador": "ecuador",
    "Peru": "peru",
    "Bolivia": "bolivia",
    "Chile": "chile",
    "Argentina": "argentina",
    "Uruguay": "uruguay",
    "Paraguay": "paraguay",
    "Brazil": "brazil|brasil",
    "Egypt": "egypt",
    "Morocco": "morocco",
    "Algeria": "algeria",
    "Tunisia": "tunisia",
    "Ethiopia": "ethiopia",
    "Kenya": "kenya",
    "Uganda": "uganda",
    "Tanzania": "tanzania",
    "Rwanda": "rwanda",
    "Nigeria": "nigeria",
    "Ghana": "ghana",
    "Senegal": "senegal",
    "Cameroon": "cameroon",
    "Ivory Coast": "ivory coast|cote d'ivoire|cote divoire",
    "South Africa": "south africa",
    "Zimbabwe": "zimbabwe",
    "Zambia": "zambia",
    "Botswana": "botswana",
    "Namibia": "namibia",
    "Mozambique": "mozambique",
    "Angola": "angola",
    "Madagascar": "madagascar",
    "Mauritius": "mauritius",
    "Australia": "australia|new south wales|queensland|western australia|south australia|"
    "tasmania",
    "Marshall Islands": "marshall islands",
    "New Zealand": "new zealand|aotearoa|nz",
}

ISO_COUNTRIES = {
    "gb": "United Kingdom", "ie": "Ireland", "fr": "France", "de": "Germany",
    "nl": "Netherlands", "be": "Belgium", "lu": "Luxembourg", "ch": "Switzerland",
    "at": "Austria", "it": "Italy", "es": "Spain", "pt": "Portugal", "dk": "Denmark",
    "no": "Norway", "se": "Sweden", "fi": "Finland", "is": "Iceland", "pl": "Poland",
    "cz": "Czechia", "sk": "Slovakia", "hu": "Hungary", "ro": "Romania", "bg": "Bulgaria",
    "gr": "Greece", "hr": "Croatia", "rs": "Serbia", "si": "Slovenia", "ee": "Estonia",
    "lv": "Latvia", "lt": "Lithuania", "by": "Belarus", "ua": "Ukraine", "ru": "Russia",
    "tr": "Turkey", "il": "Israel", "ae": "United Arab Emirates", "sa": "Saudi Arabia",
    "eg": "Egypt", "ng": "Nigeria", "ke": "Kenya", "za": "South Africa", "ma": "Morocco",
    "in": "India", "pk": "Pakistan", "bd": "Bangladesh", "lk": "Sri Lanka", "np": "Nepal",
    "cn": "China", "hk": "Hong Kong", "tw": "Taiwan", "jp": "Japan", "kr": "South Korea",
    "sg": "Singapore", "my": "Malaysia", "id": "Indonesia", "th": "Thailand",
    "vn": "Vietnam", "ph": "Philippines", "au": "Australia", "nz": "New Zealand",
    "ca": "Canada", "mx": "Mexico", "br": "Brazil", "ar": "Argentina", "cl": "Chile",
    "co": "Colombia", "pe": "Peru", "ve": "Venezuela", "uy": "Uruguay", "ec": "Ecuador",
    "cr": "Costa Rica", "ir": "Iran", "kz": "Kazakhstan", "ge": "Georgia", "am": "Armenia",
    "az": "Azerbaijan", "al": "Albania", "md": "Moldova", "me": "Montenegro",
    "mn": "Mongolia", "mt": "Malta", "tn": "Tunisia", "uk": "United Kingdom",
}
# Codes that are both a US state and a country: after a foreign city they mean the country
# ("Berlin, DE", "Tel Aviv, IL"); otherwise the state ("Gurnee, IL").
ISO_OVERLAP = {code for code in US_STATES if code in ISO_COUNTRIES} | {
    "ga", "la", "pa", "sc", "sd", "va", "ne",
}

FOREIGN_CITIES = {
    "United Kingdom": "london|manchester|edinburgh|glasgow|leeds|liverpool|sheffield|"
    "nottingham|newcastle|brighton|cardiff|belfast|aberdeen|dundee|southampton|coventry|"
    "leicester|hull|oxfordshire|cambridgeshire",
    "Ireland": "dublin|cork|galway|limerick",
    "France": "paris|lyon|marseille|toulouse|bordeaux|lille|nantes|strasbourg|montpellier|"
    "rennes|grenoble|sophia antipolis",
    "Germany": "berlin|munich|munchen|hamburg|frankfurt|cologne|koln|stuttgart|dusseldorf|"
    "leipzig|dresden|karlsruhe|heidelberg|hannover|nuremberg|nurnberg|bonn|aachen|"
    "darmstadt|mannheim|bremen|dortmund|essen|freiburg|munster|potsdam|jena|erlangen|"
    "tubingen|ulm",
    "Netherlands": "amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|delft|leiden|"
    "groningen|nijmegen",
    "Belgium": "brussels|bruxelles|antwerp|ghent|gent|leuven|liege",
    "Switzerland": "zurich|geneva|geneve|basel|bern|lausanne|lugano|zug",
    "Austria": "vienna|wien|graz|linz|salzburg|innsbruck",
    "Italy": "rome|roma|milan|milano|turin|torino|naples|napoli|bologna|florence|firenze|"
    "pisa|genoa|genova|padua|padova|trento|bari|palermo",
    "Spain": "madrid|barcelona|valencia|seville|sevilla|bilbao|malaga|zaragoza|granada|"
    "alicante|palma",
    "Portugal": "lisbon|lisboa|porto|braga|coimbra",
    "Denmark": "copenhagen|kobenhavn|aarhus|odense",
    "Norway": "oslo|bergen|trondheim|stavanger",
    "Sweden": "stockholm|gothenburg|goteborg|malmo|uppsala|lund|linkoping",
    "Finland": "helsinki|espoo|tampere|turku|oulu",
    "Iceland": "reykjavik",
    "Estonia": "tallinn|tartu",
    "Latvia": "riga",
    "Lithuania": "vilnius|kaunas",
    "Poland": "warsaw|warszawa|krakow|wroclaw|gdansk|poznan|lodz|katowice|rzeszow",
    "Czechia": "prague|praha|brno|ostrava",
    "Slovakia": "bratislava|kosice",
    "Hungary": "budapest|debrecen",
    "Romania": "bucharest|bucuresti|cluj|cluj-napoca|iasi|timisoara",
    "Bulgaria": "sofia|plovdiv|varna",
    "Serbia": "belgrade|beograd|novi sad",
    "Croatia": "zagreb",
    "Slovenia": "ljubljana",
    "Bosnia and Herzegovina": "sarajevo",
    "North Macedonia": "skopje",
    "Albania": "tirana",
    "Moldova": "chisinau",
    "Belarus": "minsk",
    "Ukraine": "kyiv|kiev|kharkiv|lviv|dnipro|odesa|odessa",
    "Russia": "moscow|novosibirsk|yekaterinburg|kazan|nizhny novgorod|samara|voronezh",
    "Georgia": "tbilisi|batumi|kutaisi",
    "Armenia": "yerevan",
    "Azerbaijan": "baku",
    "Greece": "thessaloniki",
    "Turkey": "istanbul|ankara|izmir|bursa|antalya",
    "Israel": "tel aviv|jerusalem|haifa|beersheba|herzliya",
    "United Arab Emirates": "dubai|abu dhabi|sharjah",
    "Saudi Arabia": "riyadh|jeddah|dammam",
    "Qatar": "doha",
    "Bahrain": "manama",
    "Kuwait": "kuwait city",
    "Oman": "muscat",
    "Jordan": "amman",
    "Lebanon": "beirut",
    "Iran": "tehran|isfahan|shiraz|mashhad|tabriz",
    "Iraq": "baghdad|erbil",
    "Egypt": "cairo|giza",
    "Nigeria": "lagos|abuja|ibadan|port harcourt",
    "Ghana": "accra|kumasi",
    "Kenya": "nairobi|mombasa",
    "Uganda": "kampala",
    "Rwanda": "kigali",
    "Ethiopia": "addis ababa",
    "Tanzania": "dar es salaam",
    "South Africa": "johannesburg|cape town|pretoria|durban",
    "Morocco": "casablanca|rabat|marrakech",
    "Tunisia": "tunis",
    "Algeria": "algiers",
    "Senegal": "dakar",
    "Ivory Coast": "abidjan",
    "Cameroon": "douala|yaounde",
    "Zimbabwe": "harare",
    "Zambia": "lusaka",
    "Botswana": "gaborone",
    "India": "mumbai|bombay|delhi|new delhi|bangalore|bengaluru|hyderabad|chennai|madras|"
    "pune|kolkata|calcutta|ahmedabad|jaipur|noida|gurgaon|gurugram|kochi|cochin|"
    "thiruvananthapuram|trivandrum|coimbatore|indore|bhopal|chandigarh|lucknow|kanpur|"
    "nagpur|surat|vadodara|visakhapatnam|vijayawada|bhubaneswar|patna|ranchi|guwahati|"
    "jodhpur|udaipur|mysore|mysuru|mangalore|ernakulam|karnataka|maharashtra|tamil nadu|"
    "telangana|andhra pradesh|gujarat|rajasthan|uttar pradesh|west bengal|haryana|"
    "madhya pradesh|bihar|odisha|assam|kerala|punjab",
    "Pakistan": "karachi|lahore|islamabad|rawalpindi|faisalabad|peshawar",
    "Bangladesh": "dhaka|chittagong",
    "Sri Lanka": "colombo|kandy",
    "Nepal": "kathmandu|pokhara",
    "China": "beijing|shanghai|shenzhen|hangzhou|guangzhou|chengdu|wuhan|nanjing|xian|xi'an|"
    "suzhou|tianjin|chongqing|xiamen|hefei|changsha|qingdao|dalian|harbin|jinan|zhengzhou|"
    "kunming|fuzhou|ningbo|shenyang|zhuhai|dongguan|foshan|xichang|yancheng|nanning|"
    "guang zhou|su zhou|shang hai|bei jing|shen zhen|hang zhou|nan jing|cheng du|wu han|"
    "chong qing|tian jin|xi an|guangdong|jiangsu|zhejiang|shandong|sichuan|hubei|hunan|henan|"
    "hebei|fujian|anhui|liaoning|shaanxi|shanxi|jiangxi|heilongjiang|jilin|guangxi|guizhou|"
    "yunnan|hainan|gansu|inner mongolia|xinjiang|ningxia|qinghai",
    "Hong Kong": "kowloon",
    "Taiwan": "taipei|hsinchu|taichung|kaohsiung|tainan",
    "Japan": "tokyo|osaka|kyoto|yokohama|nagoya|fukuoka|sapporo|kobe|sendai|hiroshima|"
    "tsukuba|aizu",
    "South Korea": "seoul|busan|incheon|daejeon|daegu|gwangju|pangyo|seongnam|suwon",
    "Mongolia": "ulaanbaatar",
    "Malaysia": "kuala lumpur|penang|johor bahru",
    "Indonesia": "jakarta|bandung|surabaya|yogyakarta|jogja|bali|denpasar|medan|malang|semarang",
    "Thailand": "bangkok|chiang mai|phuket",
    "Vietnam": "hanoi|ha noi|ho chi minh city|ho chi minh|saigon|da nang",
    "Philippines": "manila|makati|quezon city|cebu|davao|taguig|pasig",
    "Cambodia": "phnom penh",
    "Myanmar": "yangon",
    "Kazakhstan": "almaty|astana",
    "Uzbekistan": "tashkent",
    "Kyrgyzstan": "bishkek",
    "Australia": "sydney|melbourne|brisbane|perth|adelaide|canberra|hobart|gold coast|darwin",
    "New Zealand": "auckland|wellington|christchurch|dunedin",
    "Canada": "toronto|montreal|vancouver|ottawa|calgary|edmonton|winnipeg|quebec city|halifax|"
    "kitchener|mississauga|markham|burnaby|richmond hill|oakville|saskatoon|laval|gatineau|"
    "kelowna|guelph",
    "Mexico": "mexico city|ciudad de mexico|cdmx|guadalajara|monterrey|puebla|tijuana|merida|"
    "queretaro",
    "Colombia": "bogota|medellin|barranquilla|cartagena",
    "Peru": "lima|arequipa",
    "Chile": "santiago|valparaiso",
    "Argentina": "buenos aires|cordoba|rosario|mendoza",
    "Uruguay": "montevideo",
    "Paraguay": "asuncion",
    "Bolivia": "la paz",
    "Ecuador": "quito|guayaquil",
    "Venezuela": "caracas|maracaibo",
    "Brazil": "sao paulo|rio de janeiro|belo horizonte|porto alegre|curitiba|recife|"
    "fortaleza|brasilia|florianopolis|campinas|goiania|manaus|belem|cuiaba|teresina|"
    "campo grande",
    "Cuba": "havana",
    "Dominican Republic": "santo domingo",
    "Guatemala": "guatemala city",
    "El Salvador": "san salvador",
    "Honduras": "tegucigalpa",
    "Nicaragua": "managua",
}

REGIONS = (
    "europe", "eu", "european union", "asia", "africa", "oceania", "latin america",
    "south america", "central america", "middle east", "scandinavia", "nordics",
    "southeast asia", "south east asia", "east asia", "south asia", "west africa",
    "east africa", "balkans", "emea", "apac", "latam",
)

UNKNOWN_MARKERS = {
    "earth", "planet earth", "the earth", "world", "the world", "worldwide", "world wide",
    "global", "globe", "international", "internet", "the internet", "online", "remote",
    "fully remote", "anywhere", "everywhere", "nowhere", "somewhere", "here", "home",
    "localhost", "cloud", "the cloud", "metaverse", "cyberspace", "universe", "the universe",
    "galaxy", "milky way", "solar system", "mars", "moon", "the moon", "space", "outer space",
    "matrix", "the matrix", "terra", "gaia", "na", "none", "null", "nil", "undefined",
    "unknown", "private", "secret", "north america", "americas", "the americas",
    "digital nomad", "nomad", "web", "the web", "github",
}

# Place names written in other scripts, matched as plain substrings.
NON_LATIN = {
    "旧金山": ("bay", "CA"), "舊金山": ("bay", "CA"), "硅谷": ("bay", "CA"), "矽谷": ("bay", "CA"),
    "サンフランシスコ": ("bay", "CA"), "샌프란시스코": ("bay", "CA"),
    "美国": ("us", None), "美國": ("us", None), "アメリカ": ("us", None), "미국": ("us", None),
    "纽约": ("us_city", "NY"), "紐約": ("us_city", "NY"), "加州": ("state", "CA"),
    "中国": ("country", "China"), "中國": ("country", "China"), "北京": ("country", "China"),
    "上海": ("country", "China"), "深圳": ("country", "China"), "杭州": ("country", "China"),
    "广州": ("country", "China"), "廣州": ("country", "China"), "成都": ("country", "China"),
    "武汉": ("country", "China"), "南京": ("country", "China"), "西安": ("country", "China"),
    "苏州": ("country", "China"), "天津": ("country", "China"), "重庆": ("country", "China"),
    "香港": ("country", "Hong Kong"), "台湾": ("country", "Taiwan"),
    "台灣": ("country", "Taiwan"), "台北": ("country", "Taiwan"), "臺北": ("country", "Taiwan"),
    "日本": ("country", "Japan"), "東京": ("country", "Japan"), "东京": ("country", "Japan"),
    "大阪": ("country", "Japan"), "京都": ("country", "Japan"),
    "한국": ("country", "South Korea"), "대한민국": ("country", "South Korea"),
    "서울": ("country", "South Korea"), "부산": ("country", "South Korea"),
    "россия": ("country", "Russia"), "москва": ("country", "Russia"),
    "україна": ("country", "Ukraine"), "київ": ("country", "Ukraine"),
    "耶路撒冷": ("country", "Israel"),
    **{name: ("country", "China") for name in (
        "山东", "济南", "云南", "江苏", "浙江", "广东", "四川", "湖北", "湖南", "福建", "河南",
        "河北", "安徽", "辽宁", "陕西", "山西", "江西", "黑龙江", "吉林", "广西", "贵州", "海南",
    )},
}

# --- Matching --------------------------------------------------------------------------------


class Token(NamedTuple):
    kind: str          # bay, us_city, foreign_city, ambiguous, unrecognized, or a qualifier kind
    value: object      # state code, country name, or None
    name: str          # the matched text


QUALIFIER_KINDS = {"code", "state", "us", "province", "country", "region", "georgia"}
REGION = "region"


def _build_phrases() -> dict[str, tuple[str, object]]:
    """Every known place name, mapped to (kind, value). Later entries win on clashes."""
    phrases: dict[str, tuple[str, object]] = {}
    for country, names in COUNTRIES.items():
        for name in names.split("|"):
            phrases[name] = ("country", country)
    for name in REGIONS:
        phrases[name] = ("region", None)
    for country, names in FOREIGN_CITIES.items():
        for name in names.split("|"):
            phrases[name] = ("foreign_city", country)
    for name in CA_PROVINCES:
        phrases[name] = ("province", None)
    for code, name in US_STATES.items():
        phrases[name] = ("state", code.upper())
    for name, state in US_CITIES.items():
        phrases[name] = ("us_city", state)
    for name in AMBIGUOUS:
        phrases[name] = ("ambiguous", None)
    for name in BAY_PLACES:
        phrases[name] = ("bay", "CA")
    for name in US_NAMES:
        phrases[name] = ("us", None)
    phrases["georgia"] = ("georgia", None)
    return phrases


PHRASES = _build_phrases()
# Short tokens that only count when they are the whole part ("LA", "NY"), so they don't
# fire inside longer names.
EXACT_ONLY = {"ny": ("state", "NY"), "la": ("us_city", "CA"), "uk": ("country", "United Kingdom")}
_SEARCHABLE = sorted((p for p in PHRASES if len(p) > 2 or p == "sf"), key=len, reverse=True)
_PHRASE_RE = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, _SEARCHABLE)) + r")(?!\w)")


_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def _flag(match: re.Match) -> str:
    """A flag emoji (two regional-indicator letters) as a country name part."""
    code = "".join(chr(ord(c) - 0x1F1E6 + ord("a")) for c in match.group(0))
    if code == "us":
        return ", usa, "
    country = ISO_COUNTRIES.get(code)
    if country == "Georgia":
        return ", sakartvelo, "
    return f", {country.lower()}, " if country else ", "


def _split(raw: str) -> list[str]:
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text:
        return []
    text = _FLAG_RE.sub(_flag, text)
    # "Austin TX" or "San Francisco CA 94107": a trailing capitalised code acts as a qualifier
    text = re.sub(
        r"(?<=[A-Za-z.])\s+([A-Z]{2})(?=\s*(?:\d{5}(?:-\d{4})?)?\s*(?:[,/|;()]|$))",
        r", \1",
        text,
    )
    text = text.lower()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    for old, new in (("u.s.a.", "usa"), ("u.s.a", "usa"), ("u.s.", "us"), ("u.k.", "uk"),
                     ("s.f.", "sf"), ("d.c.", "dc")):
        text = text.replace(old, new)
    text = re.sub(r"\bst\.?\s+", "saint ", text)
    text = re.sub(r"\bft\.\s*", "fort ", text)
    text = re.sub(r"\bwashington,?\s*dc\b", "washington dc", text)
    text = re.sub(r"\b\d{5}(?:-\d{4})?\b", " ", text)
    text = re.sub(r"\s+-\s+|[|/;()\[\]{}·•–—]|\s&\s|\s\+\s", ",", text)
    text = re.sub(r"[^\w\s,.'-]", " ", text)
    parts = []
    for part in text.split(","):
        part = re.sub(r"\s+", " ", part).strip(" .'-_")
        if part:
            parts.append(part)
    return parts


def _match(part: str, index: int) -> Token | None:
    # A bare two-letter part after a comma is a state, province or country code ("SF" and "US"
    # excepted)
    if index > 0 and len(part) == 2 and part.isascii() and part.isalpha():
        if part in ("sf", "us"):
            kind, value = PHRASES[part]
            return Token(kind, value, part)
        return Token("code", part, part)
    if part in UNKNOWN_MARKERS:
        return Token("unknown", None, part)
    exact = EXACT_ONLY.get(part) or PHRASES.get(part)
    if exact:
        return Token(exact[0], exact[1], part)
    found = _PHRASE_RE.search(part)
    if found:
        kind, value = PHRASES[found.group(0)]
        return Token(kind, value, found.group(0))
    for name, (kind, value) in NON_LATIN.items():
        if name in part:
            return Token(kind, value, name)
    return None


@dataclass
class _Group:
    head: Token | None = None
    quals: list[Token] = field(default_factory=list)


def _resolve(group: _Group) -> Place | None:
    head = group.head
    kind = head.kind if head else None
    foreign_head = kind == "foreign_city" and head.name not in BAY_IF_CALIFORNIA
    country: str | None = None  # "US", "Canada", REGION or another country name
    state: str | None = None
    georgia = False
    # Spelled-out qualifiers decide first. Two-letter codes are ambiguous ("MS" is Mississippi
    # and a Brazilian state), so they only decide when nothing spelled out did.
    for q in group.quals:
        decided = None
        if q.kind == "state":
            decided, state = "US", state or q.value
        elif q.kind == "us":
            decided = "US"
        elif q.kind == "province":
            decided = "Canada"
        elif q.kind == "country":
            decided = q.value
        elif q.kind == "region":
            decided = REGION
        elif q.kind == "georgia":
            georgia = True
        if decided and country is None:
            country = decided
    for code in (q.value for q in group.quals if q.kind == "code"):
        if country is None:
            if code in CA_PROVINCE_CODES:
                country = "Canada"
            elif foreign_head and code in ISO_OVERLAP:
                country = head.value  # "Berlin, DE": the country of the city
            elif code in US_STATES:
                country, state = "US", code.upper()
            elif code in ISO_COUNTRIES:
                country = ISO_COUNTRIES[code]
            elif foreign_head:
                country = head.value
        elif country == "US" and state is None and code in US_STATES:
            state = code.upper()

    if georgia:  # the US state or the country, depending on the place before it
        if foreign_head and country is None:
            country = "Georgia"
        elif country is None and head is not None:
            country, state = "US", "GA"
        elif country == "US" and state is None:
            state = "GA"

    if country == "US":
        if state is None and kind == "us_city":
            state = head.value
        in_bay = (kind == "bay" and state in (None, "CA")) or (
            head is not None and head.name in BAY_IF_CALIFORNIA and state == "CA"
        )
        return Place(BAY, "CA", USA) if in_bay else Place(US, state, USA)
    if country == REGION:
        return Place(OUTSIDE)
    if country:
        return Place(OUTSIDE, None, country)
    if kind == "bay":
        return Place(BAY, "CA", USA)
    if kind == "us_city":
        return Place(US, head.value, USA)
    if kind == "foreign_city":
        return Place(OUTSIDE, None, head.value)
    return None  # ambiguous or unrecognised name with nothing to settle it


def classify(location: str | None) -> Place:
    """Section (and state or country, when known) for a GitHub profile location."""
    groups: list[_Group] = []
    for index, part in enumerate(_split(location or "")):
        token = _match(part, index) or Token("unrecognized", None, part)
        if token.kind == "unknown":
            continue
        if token.kind in QUALIFIER_KINDS:
            if not groups:
                groups.append(_Group())
            groups[-1].quals.append(token)
        else:
            groups.append(_Group(head=token))
    places = [place for place in map(_resolve, groups) if place is not None]
    for section in (BAY, US):
        for place in places:
            if place.section == section:
                return place
    return places[0] if places else UNKNOWN_PLACE
