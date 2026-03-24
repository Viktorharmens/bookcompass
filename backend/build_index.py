"""
build_index.py — Éénmalig script om de FAISS-index te bouwen.

Gebruik:  python build_index.py
"""

import asyncio
import json
import os
import numpy as np
import faiss
import httpx

from embedder import embed_book, get_model

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SEED_BOOKS = [
    # ── 19e-eeuwse Engelse klassieken ─────────────────────────────────────
    {"key": "/works/OL15413W",    "title": "Pride and Prejudice",              "author": "Jane Austen"},
    {"key": "/works/OL20925360W", "title": "Emma",                             "author": "Jane Austen"},
    {"key": "/works/OL52122W",    "title": "Sense and Sensibility",            "author": "Jane Austen"},
    {"key": "/works/OL53924W",    "title": "Persuasion",                       "author": "Jane Austen"},
    {"key": "/works/OL52123W",    "title": "Northanger Abbey",                 "author": "Jane Austen"},
    {"key": "/works/OL52124W",    "title": "Mansfield Park",                   "author": "Jane Austen"},
    {"key": "/works/OL118317W",   "title": "Jane Eyre",                        "author": "Charlotte Brontë"},
    {"key": "/works/OL58638W",    "title": "Wuthering Heights",                "author": "Emily Brontë"},
    {"key": "/works/OL51861W",    "title": "Great Expectations",               "author": "Charles Dickens"},
    {"key": "/works/OL14860294W", "title": "A Tale of Two Cities",             "author": "Charles Dickens"},
    {"key": "/works/OL55000W",    "title": "David Copperfield",                "author": "Charles Dickens"},
    {"key": "/works/OL12909W",    "title": "Oliver Twist",                     "author": "Charles Dickens"},
    {"key": "/works/OL14843W",    "title": "Bleak House",                      "author": "Charles Dickens"},
    {"key": "/works/OL20553W",    "title": "Middlemarch",                      "author": "George Eliot"},
    {"key": "/works/OL20554W",    "title": "The Mill on the Floss",            "author": "George Eliot"},
    {"key": "/works/OL52946W",    "title": "Moby Dick",                        "author": "Herman Melville"},
    {"key": "/works/OL76514W",    "title": "Adventures of Huckleberry Finn",   "author": "Mark Twain"},
    {"key": "/works/OL76504W",    "title": "The Adventures of Tom Sawyer",     "author": "Mark Twain"},
    {"key": "/works/OL16328W",    "title": "The Scarlet Letter",               "author": "Nathaniel Hawthorne"},
    {"key": "/works/OL12880W",    "title": "Tess of the d'Urbervilles",        "author": "Thomas Hardy"},
    {"key": "/works/OL12881W",    "title": "Far from the Madding Crowd",       "author": "Thomas Hardy"},
    {"key": "/works/OL162965W",   "title": "The Picture of Dorian Gray",       "author": "Oscar Wilde"},
    {"key": "/works/OL148297W",   "title": "Dracula",                          "author": "Bram Stoker"},
    {"key": "/works/OL149332W",   "title": "Frankenstein",                     "author": "Mary Shelley"},
    {"key": "/works/OL92963W",    "title": "The Turn of the Screw",            "author": "Henry James"},
    {"key": "/works/OL92964W",    "title": "The Portrait of a Lady",           "author": "Henry James"},
    {"key": "/works/OL8449025W",  "title": "Heart of Darkness",                "author": "Joseph Conrad"},
    {"key": "/works/OL8449026W",  "title": "Lord Jim",                         "author": "Joseph Conrad"},

    # ── Vroeg 20e eeuw ───────────────────────────────────────────────────
    {"key": "/works/OL27482W",    "title": "The Great Gatsby",                 "author": "F. Scott Fitzgerald"},
    {"key": "/works/OL8479324W",  "title": "Tender is the Night",              "author": "F. Scott Fitzgerald"},
    {"key": "/works/OL17853W",    "title": "The Sun Also Rises",               "author": "Ernest Hemingway"},
    {"key": "/works/OL27448W",    "title": "A Farewell to Arms",               "author": "Ernest Hemingway"},
    {"key": "/works/OL15322246W", "title": "For Whom the Bell Tolls",          "author": "Ernest Hemingway"},
    {"key": "/works/OL17860W",    "title": "Ulysses",                          "author": "James Joyce"},
    {"key": "/works/OL66213W",    "title": "Dubliners",                        "author": "James Joyce"},
    {"key": "/works/OL30257W",    "title": "Mrs Dalloway",                     "author": "Virginia Woolf"},
    {"key": "/works/OL15334W",    "title": "To the Lighthouse",                "author": "Virginia Woolf"},
    {"key": "/works/OL8479317W",  "title": "A Room with a View",               "author": "E.M. Forster"},
    {"key": "/works/OL8479318W",  "title": "Howards End",                      "author": "E.M. Forster"},
    {"key": "/works/OL8479319W",  "title": "A Passage to India",               "author": "E.M. Forster"},
    {"key": "/works/OL8479321W",  "title": "Sons and Lovers",                  "author": "D.H. Lawrence"},
    {"key": "/works/OL8479323W",  "title": "Lady Chatterley's Lover",          "author": "D.H. Lawrence"},
    {"key": "/works/OL8479325W",  "title": "The Quiet American",               "author": "Graham Greene"},
    {"key": "/works/OL8479326W",  "title": "The Power and the Glory",          "author": "Graham Greene"},
    {"key": "/works/OL8479327W",  "title": "Brighton Rock",                    "author": "Graham Greene"},
    {"key": "/works/OL8479329W",  "title": "Brideshead Revisited",             "author": "Evelyn Waugh"},
    {"key": "/works/OL8479330W",  "title": "A Handful of Dust",                "author": "Evelyn Waugh"},
    {"key": "/works/OL14991615W", "title": "Brave New World",                  "author": "Aldous Huxley"},
    {"key": "/works/OL98827W",    "title": "1984",                             "author": "George Orwell"},
    {"key": "/works/OL53908W",    "title": "Animal Farm",                      "author": "George Orwell"},
    {"key": "/works/OL66554W",    "title": "Lord of the Flies",                "author": "William Golding"},
    {"key": "/works/OL102749W",   "title": "To Kill a Mockingbird",            "author": "Harper Lee"},
    {"key": "/works/OL262W",      "title": "The Catcher in the Rye",           "author": "J.D. Salinger"},
    {"key": "/works/OL36244W",    "title": "Of Mice and Men",                  "author": "John Steinbeck"},
    {"key": "/works/OL8479314W",  "title": "The Grapes of Wrath",              "author": "John Steinbeck"},
    {"key": "/works/OL8479315W",  "title": "East of Eden",                     "author": "John Steinbeck"},
    {"key": "/works/OL16335979W", "title": "Lolita",                           "author": "Vladimir Nabokov"},
    {"key": "/works/OL22744W",    "title": "Catch-22",                         "author": "Joseph Heller"},
    {"key": "/works/OL15548W",    "title": "Slaughterhouse-Five",              "author": "Kurt Vonnegut"},
    {"key": "/works/OL34125W",    "title": "On the Road",                      "author": "Jack Kerouac"},
    {"key": "/works/OL17723W",    "title": "The Bell Jar",                     "author": "Sylvia Plath"},
    {"key": "/works/OL8479304W",  "title": "One Flew Over the Cuckoo's Nest",  "author": "Ken Kesey"},
    {"key": "/works/OL8479346W",  "title": "A Clockwork Orange",               "author": "Anthony Burgess"},
    {"key": "/works/OL8479347W",  "title": "The French Lieutenant's Woman",    "author": "John Fowles"},
    {"key": "/works/OL8479337W",  "title": "Rabbit, Run",                      "author": "John Updike"},
    {"key": "/works/OL8479338W",  "title": "Herzog",                           "author": "Saul Bellow"},
    {"key": "/works/OL8479340W",  "title": "Portnoy's Complaint",              "author": "Philip Roth"},
    {"key": "/works/OL8479341W",  "title": "American Pastoral",                "author": "Philip Roth"},
    {"key": "/works/OL8479342W",  "title": "The Human Stain",                  "author": "Philip Roth"},
    {"key": "/works/OL8479343W",  "title": "The Plot Against America",         "author": "Philip Roth"},
    {"key": "/works/OL8479333W",  "title": "Invisible Man",                    "author": "Ralph Ellison"},
    {"key": "/works/OL8479334W",  "title": "Native Son",                       "author": "Richard Wright"},
    {"key": "/works/OL8479335W",  "title": "Giovanni's Room",                  "author": "James Baldwin"},
    {"key": "/works/OL8479336W",  "title": "Go Tell It on the Mountain",       "author": "James Baldwin"},
    {"key": "/works/OL894936W",   "title": "Beloved",                          "author": "Toni Morrison"},
    {"key": "/works/OL8479331W",  "title": "Song of Solomon",                  "author": "Toni Morrison"},
    {"key": "/works/OL8479332W",  "title": "The Bluest Eye",                   "author": "Toni Morrison"},
    {"key": "/works/OL12395W",    "title": "The Color Purple",                 "author": "Alice Walker"},
    {"key": "/works/OL455743W",   "title": "Their Eyes Were Watching God",     "author": "Zora Neale Hurston"},
    {"key": "/works/OL17719W",    "title": "The Stories of John Cheever",      "author": "John Cheever"},
    {"key": "/works/OL8479344W",  "title": "A Good Man Is Hard to Find",       "author": "Flannery O'Connor"},
    {"key": "/works/OL8479345W",  "title": "The Heart Is a Lonely Hunter",     "author": "Carson McCullers"},
    {"key": "/works/OL19631W",    "title": "In Cold Blood",                    "author": "Truman Capote"},

    # ── Postmodern & experimenteel ────────────────────────────────────────
    {"key": "/works/OL1166083W",  "title": "Infinite Jest",                    "author": "David Foster Wallace"},
    {"key": "/works/OL8027283W",  "title": "White Noise",                      "author": "Don DeLillo"},
    {"key": "/works/OL8479351W",  "title": "Underworld",                       "author": "Don DeLillo"},
    {"key": "/works/OL8479155W",  "title": "The Crying of Lot 49",             "author": "Thomas Pynchon"},
    {"key": "/works/OL8479348W",  "title": "Gravity's Rainbow",                "author": "Thomas Pynchon"},
    {"key": "/works/OL8479349W",  "title": "The New York Trilogy",             "author": "Paul Auster"},
    {"key": "/works/OL3702125W",  "title": "If on a winter's night a traveler","author": "Italo Calvino"},

    # ── Laat 20e / hedendaags Brits ───────────────────────────────────────
    {"key": "/works/OL82563W",    "title": "Never Let Me Go",                  "author": "Kazuo Ishiguro"},
    {"key": "/works/OL26694W",    "title": "The Remains of the Day",           "author": "Kazuo Ishiguro"},
    {"key": "/works/OL21176151W", "title": "Klara and the Sun",                "author": "Kazuo Ishiguro"},
    {"key": "/works/OL8479362W",  "title": "The Buried Giant",                 "author": "Kazuo Ishiguro"},
    {"key": "/works/OL17335880W", "title": "Atonement",                        "author": "Ian McEwan"},
    {"key": "/works/OL26377W",    "title": "Saturday",                         "author": "Ian McEwan"},
    {"key": "/works/OL8479352W",  "title": "On Chesil Beach",                  "author": "Ian McEwan"},
    {"key": "/works/OL2956415W",  "title": "White Teeth",                      "author": "Zadie Smith"},
    {"key": "/works/OL8479353W",  "title": "NW",                               "author": "Zadie Smith"},
    {"key": "/works/OL8479354W",  "title": "On Beauty",                        "author": "Zadie Smith"},
    {"key": "/works/OL8479356W",  "title": "Midnight's Children",              "author": "Salman Rushdie"},
    {"key": "/works/OL8479357W",  "title": "The Satanic Verses",               "author": "Salman Rushdie"},
    {"key": "/works/OL8479361W",  "title": "Crossroads",                       "author": "Jonathan Franzen"},
    {"key": "/works/OL3347538W",  "title": "The Corrections",                  "author": "Jonathan Franzen"},
    {"key": "/works/OL8461444W",  "title": "Freedom",                          "author": "Jonathan Franzen"},
    {"key": "/works/OL8479404W",  "title": "Outline",                          "author": "Rachel Cusk"},
    {"key": "/works/OL8479405W",  "title": "Transit",                          "author": "Rachel Cusk"},
    {"key": "/works/OL8479406W",  "title": "Kudos",                            "author": "Rachel Cusk"},
    {"key": "/works/OL8479359W",  "title": "Paddy Clarke Ha Ha Ha",            "author": "Roddy Doyle"},
    {"key": "/works/OL8479394W",  "title": "Stoner",                           "author": "John Williams"},
    {"key": "/works/OL8479395W",  "title": "Butcher's Crossing",               "author": "John Williams"},

    # ── Hedendaagse literaire fictie (2000–2024) ──────────────────────────
    {"key": "/works/OL17860626W", "title": "A Little Life",                    "author": "Hanya Yanagihara"},
    {"key": "/works/OL8479410W",  "title": "To Paradise",                      "author": "Hanya Yanagihara"},
    {"key": "/works/OL17356707W", "title": "The Goldfinch",                    "author": "Donna Tartt"},
    {"key": "/works/OL1966765W",  "title": "The Secret History",               "author": "Donna Tartt"},
    {"key": "/works/OL17353286W", "title": "All the Light We Cannot See",      "author": "Anthony Doerr"},
    {"key": "/works/OL20652819W", "title": "Pachinko",                         "author": "Min Jin Lee"},
    {"key": "/works/OL20108805W", "title": "The Sympathizer",                  "author": "Viet Thanh Nguyen"},
    {"key": "/works/OL20739336W", "title": "Lincoln in the Bardo",             "author": "George Saunders"},
    {"key": "/works/OL21176148W", "title": "Normal People",                    "author": "Sally Rooney"},
    {"key": "/works/OL20739340W", "title": "Conversations with Friends",       "author": "Sally Rooney"},
    {"key": "/works/OL21176149W", "title": "Beautiful World, Where Are You",   "author": "Sally Rooney"},
    {"key": "/works/OL8479411W",  "title": "Intermezzo",                       "author": "Sally Rooney"},
    {"key": "/works/OL21176150W", "title": "Piranesi",                         "author": "Susanna Clarke"},
    {"key": "/works/OL17336046W", "title": "Jonathan Strange & Mr Norrell",    "author": "Susanna Clarke"},
    {"key": "/works/OL21176152W", "title": "The Midnight Library",             "author": "Matt Haig"},
    {"key": "/works/OL21176155W", "title": "Where the Crawdads Sing",          "author": "Delia Owens"},
    {"key": "/works/OL21176156W", "title": "The Dutch House",                  "author": "Ann Patchett"},
    {"key": "/works/OL21176157W", "title": "Demon Copperhead",                 "author": "Barbara Kingsolver"},
    {"key": "/works/OL21176158W", "title": "Trust",                            "author": "Hernan Diaz"},
    {"key": "/works/OL21176159W", "title": "Tomorrow, and Tomorrow, and Tomorrow", "author": "Gabrielle Zevin"},
    {"key": "/works/OL8479363W",  "title": "A Visit from the Goon Squad",      "author": "Jennifer Egan"},
    {"key": "/works/OL8479365W",  "title": "The Underground Railroad",         "author": "Colson Whitehead"},
    {"key": "/works/OL8479367W",  "title": "The Nickel Boys",                  "author": "Colson Whitehead"},
    {"key": "/works/OL8479368W",  "title": "James",                            "author": "Percival Everett"},
    {"key": "/works/OL8479370W",  "title": "Erasure",                          "author": "Percival Everett"},
    {"key": "/works/OL8479371W",  "title": "The Brief Wondrous Life of Oscar Wao", "author": "Junot Díaz"},
    {"key": "/works/OL8479373W",  "title": "Gilead",                           "author": "Marilynne Robinson"},
    {"key": "/works/OL8479374W",  "title": "Home",                             "author": "Marilynne Robinson"},
    {"key": "/works/OL8479375W",  "title": "Housekeeping",                     "author": "Marilynne Robinson"},
    {"key": "/works/OL8479376W",  "title": "The Known World",                  "author": "Edward P. Jones"},
    {"key": "/works/OL8479377W",  "title": "The Kite Runner",                  "author": "Khaled Hosseini"},
    {"key": "/works/OL8479378W",  "title": "A Thousand Splendid Suns",         "author": "Khaled Hosseini"},
    {"key": "/works/OL8479380W",  "title": "Life of Pi",                       "author": "Yann Martel"},
    {"key": "/works/OL8479381W",  "title": "The Book Thief",                   "author": "Markus Zusak"},
    {"key": "/works/OL8479383W",  "title": "The Help",                         "author": "Kathryn Stockett"},
    {"key": "/works/OL8479385W",  "title": "Little Fires Everywhere",          "author": "Celeste Ng"},
    {"key": "/works/OL8479386W",  "title": "Everything I Never Told You",      "author": "Celeste Ng"},
    {"key": "/works/OL8479388W",  "title": "Circe",                            "author": "Madeline Miller"},
    {"key": "/works/OL8479389W",  "title": "The Song of Achilles",             "author": "Madeline Miller"},
    {"key": "/works/OL8479390W",  "title": "The Night Circus",                 "author": "Erin Morgenstern"},
    {"key": "/works/OL8479391W",  "title": "The Covenant of Water",            "author": "Abraham Verghese"},
    {"key": "/works/OL8479393W",  "title": "The Overstory",                    "author": "Richard Powers"},
    {"key": "/works/OL8479392W",  "title": "Bewilderment",                     "author": "Richard Powers"},
    {"key": "/works/OL8479396W",  "title": "A Man Called Ove",                 "author": "Fredrik Backman"},
    {"key": "/works/OL8479397W",  "title": "Anxious People",                   "author": "Fredrik Backman"},
    {"key": "/works/OL8479399W",  "title": "On Earth We're Briefly Gorgeous",  "author": "Ocean Vuong"},
    {"key": "/works/OL8479400W",  "title": "There There",                      "author": "Tommy Orange"},
    {"key": "/works/OL8479402W",  "title": "My Year of Rest and Relaxation",   "author": "Ottessa Moshfegh"},
    {"key": "/works/OL8479403W",  "title": "Eileen",                           "author": "Ottessa Moshfegh"},
    {"key": "/works/OL8479384W",  "title": "Big Little Lies",                  "author": "Liane Moriarty"},
    {"key": "/works/OL8479412W",  "title": "Nine Perfect Strangers",           "author": "Liane Moriarty"},
    {"key": "/works/OL21176161W", "title": "The Women",                        "author": "Kristin Hannah"},
    {"key": "/works/OL8479413W",  "title": "The Nightingale",                  "author": "Kristin Hannah"},
    {"key": "/works/OL8479414W",  "title": "Lessons in Chemistry",             "author": "Bonnie Garmus"},
    {"key": "/works/OL8479415W",  "title": "The Maid",                         "author": "Nita Prose"},
    {"key": "/works/OL8479416W",  "title": "Remarkably Bright Creatures",      "author": "Shelby Van Pelt"},
    {"key": "/works/OL8479417W",  "title": "The Measure",                      "author": "Nikki Erlick"},
    {"key": "/works/OL8479418W",  "title": "Babel",                            "author": "R.F. Kuang"},
    {"key": "/works/OL8479419W",  "title": "Yellowface",                       "author": "R.F. Kuang"},
    {"key": "/works/OL8479420W",  "title": "The Bee Sting",                    "author": "Paul Murray"},
    {"key": "/works/OL8479421W",  "title": "Skippy Dies",                      "author": "Paul Murray"},
    {"key": "/works/OL8479422W",  "title": "James",                            "author": "Percival Everett"},
    {"key": "/works/OL8479423W",  "title": "Prophet Song",                     "author": "Paul Lynch"},
    {"key": "/works/OL8479424W",  "title": "The Pale King",                    "author": "David Foster Wallace"},
    {"key": "/works/OL8479425W",  "title": "A Gentleman in Moscow",            "author": "Amor Towles"},
    {"key": "/works/OL8479426W",  "title": "Rules of Civility",                "author": "Amor Towles"},
    {"key": "/works/OL8479427W",  "title": "Lincoln Highway",                  "author": "Amor Towles"},
    {"key": "/works/OL8479428W",  "title": "The Seven Husbands of Evelyn Hugo","author": "Taylor Jenkins Reid"},
    {"key": "/works/OL8479429W",  "title": "Daisy Jones & The Six",            "author": "Taylor Jenkins Reid"},
    {"key": "/works/OL8479430W",  "title": "Malibu Rising",                    "author": "Taylor Jenkins Reid"},
    {"key": "/works/OL8479431W",  "title": "The Vanishing Half",               "author": "Brit Bennett"},
    {"key": "/works/OL8479432W",  "title": "Homegoing",                        "author": "Yaa Gyasi"},
    {"key": "/works/OL8479433W",  "title": "Transcendent Kingdom",             "author": "Yaa Gyasi"},
    {"key": "/works/OL8479434W",  "title": "Memorial",                         "author": "Bryan Washington"},
    {"key": "/works/OL8479435W",  "title": "Detransition, Baby",               "author": "Torrey Peters"},
    {"key": "/works/OL8479436W",  "title": "Shuggie Bain",                     "author": "Douglas Stuart"},
    {"key": "/works/OL8479437W",  "title": "Young Mungo",                      "author": "Douglas Stuart"},
    {"key": "/works/OL8479438W",  "title": "The Marriage Portrait",            "author": "Maggie O'Farrell"},
    {"key": "/works/OL8479439W",  "title": "Hamnet",                           "author": "Maggie O'Farrell"},
    {"key": "/works/OL8479440W",  "title": "The Mountains Sing",               "author": "Nguyen Phan Que Mai"},
    {"key": "/works/OL8479441W",  "title": "Crying in H Mart",                 "author": "Michelle Zauner"},

    # ── Historische fictie ────────────────────────────────────────────────
    {"key": "/works/OL8479442W",  "title": "Wolf Hall",                        "author": "Hilary Mantel"},
    {"key": "/works/OL8479443W",  "title": "Bring Up the Bodies",              "author": "Hilary Mantel"},
    {"key": "/works/OL8479444W",  "title": "The Mirror and the Light",         "author": "Hilary Mantel"},
    {"key": "/works/OL8479445W",  "title": "Pillars of the Earth",             "author": "Ken Follett"},
    {"key": "/works/OL8479446W",  "title": "World Without End",                "author": "Ken Follett"},
    {"key": "/works/OL8479447W",  "title": "Outlander",                        "author": "Diana Gabaldon"},
    {"key": "/works/OL8479448W",  "title": "The Name of the Rose",             "author": "Umberto Eco"},
    {"key": "/works/OL8479449W",  "title": "Girl with a Pearl Earring",        "author": "Tracy Chevalier"},
    {"key": "/works/OL8479450W",  "title": "The Bronze Horseman",              "author": "Paullina Simons"},
    {"key": "/works/OL8479451W",  "title": "The Alice Network",                "author": "Kate Quinn"},
    {"key": "/works/OL8479452W",  "title": "The Rose Code",                    "author": "Kate Quinn"},
    {"key": "/works/OL8479453W",  "title": "Fingersmith",                      "author": "Sarah Waters"},
    {"key": "/works/OL8479454W",  "title": "Affinity",                         "author": "Sarah Waters"},
    {"key": "/works/OL8479455W",  "title": "Tipping the Velvet",               "author": "Sarah Waters"},
    {"key": "/works/OL8479456W",  "title": "The Hours",                        "author": "Michael Cunningham"},
    {"key": "/works/OL8479457W",  "title": "Cold Mountain",                    "author": "Charles Frazier"},
    {"key": "/works/OL8479458W",  "title": "Loving",                           "author": "Henry Green"},
    {"key": "/works/OL8479459W",  "title": "The Paris Wife",                   "author": "Paula McLain"},

    # ── Science Fiction ───────────────────────────────────────────────────
    {"key": "/works/OL27258W",    "title": "Dune",                             "author": "Frank Herbert"},
    {"key": "/works/OL8479460W",  "title": "Dune Messiah",                     "author": "Frank Herbert"},
    {"key": "/works/OL893580W",   "title": "Foundation",                       "author": "Isaac Asimov"},
    {"key": "/works/OL8479461W",  "title": "I, Robot",                         "author": "Isaac Asimov"},
    {"key": "/works/OL10317W",    "title": "The Left Hand of Darkness",        "author": "Ursula K. Le Guin"},
    {"key": "/works/OL8069710W",  "title": "The Dispossessed",                 "author": "Ursula K. Le Guin"},
    {"key": "/works/OL8479158W",  "title": "A Wizard of Earthsea",             "author": "Ursula K. Le Guin"},
    {"key": "/works/OL8479228W",  "title": "Fahrenheit 451",                   "author": "Ray Bradbury"},
    {"key": "/works/OL32W",       "title": "The Martian Chronicles",           "author": "Ray Bradbury"},
    {"key": "/works/OL15548W",    "title": "Slaughterhouse-Five",              "author": "Kurt Vonnegut"},
    {"key": "/works/OL17330219W", "title": "The Handmaid's Tale",              "author": "Margaret Atwood"},
    {"key": "/works/OL8479462W",  "title": "The Testaments",                   "author": "Margaret Atwood"},
    {"key": "/works/OL8479463W",  "title": "Oryx and Crake",                   "author": "Margaret Atwood"},
    {"key": "/works/OL263234W",   "title": "Ender's Game",                     "author": "Orson Scott Card"},
    {"key": "/works/OL81353W",    "title": "Neuromancer",                      "author": "William Gibson"},
    {"key": "/works/OL8479464W",  "title": "Pattern Recognition",              "author": "William Gibson"},
    {"key": "/works/OL8085790W",  "title": "The Road",                         "author": "Cormac McCarthy"},
    {"key": "/works/OL17338715W", "title": "Blood Meridian",                   "author": "Cormac McCarthy"},
    {"key": "/works/OL8479465W",  "title": "No Country for Old Men",           "author": "Cormac McCarthy"},
    {"key": "/works/OL17863936W", "title": "Station Eleven",                   "author": "Emily St. John Mandel"},
    {"key": "/works/OL8479466W",  "title": "The Glass Hotel",                  "author": "Emily St. John Mandel"},
    {"key": "/works/OL8479467W",  "title": "Sea of Tranquility",               "author": "Emily St. John Mandel"},
    {"key": "/works/OL20022515W", "title": "The Three-Body Problem",           "author": "Liu Cixin"},
    {"key": "/works/OL8479468W",  "title": "The Dark Forest",                  "author": "Liu Cixin"},
    {"key": "/works/OL8479469W",  "title": "Recursion",                        "author": "Blake Crouch"},
    {"key": "/works/OL8479470W",  "title": "Dark Matter",                      "author": "Blake Crouch"},
    {"key": "/works/OL8479471W",  "title": "Upgrade",                          "author": "Blake Crouch"},
    {"key": "/works/OL21176153W", "title": "Project Hail Mary",                "author": "Andy Weir"},
    {"key": "/works/OL21176154W", "title": "The Martian",                      "author": "Andy Weir"},
    {"key": "/works/OL8479472W",  "title": "The Fifth Season",                 "author": "N.K. Jemisin"},
    {"key": "/works/OL8479473W",  "title": "The Obelisk Gate",                 "author": "N.K. Jemisin"},
    {"key": "/works/OL8479474W",  "title": "The Stone Sky",                    "author": "N.K. Jemisin"},
    {"key": "/works/OL8479475W",  "title": "Ancillary Justice",                "author": "Ann Leckie"},
    {"key": "/works/OL8479476W",  "title": "Kindred",                          "author": "Octavia Butler"},
    {"key": "/works/OL8479477W",  "title": "Parable of the Sower",             "author": "Octavia Butler"},
    {"key": "/works/OL8479478W",  "title": "Exhalation",                       "author": "Ted Chiang"},
    {"key": "/works/OL8479479W",  "title": "Stories of Your Life and Others",  "author": "Ted Chiang"},
    {"key": "/works/OL8479480W",  "title": "All Systems Red",                  "author": "Martha Wells"},
    {"key": "/works/OL8479481W",  "title": "The Long Way to a Small Angry Planet","author": "Becky Chambers"},
    {"key": "/works/OL8479482W",  "title": "A Memory Called Empire",           "author": "Arkady Martine"},
    {"key": "/works/OL8479483W",  "title": "The Power",                        "author": "Naomi Alderman"},
    {"key": "/works/OL8479484W",  "title": "Flowers for Algernon",             "author": "Daniel Keyes"},
    {"key": "/works/OL8479485W",  "title": "Do Androids Dream of Electric Sheep","author": "Philip K. Dick"},
    {"key": "/works/OL8479486W",  "title": "The Man in the High Castle",       "author": "Philip K. Dick"},
    {"key": "/works/OL8479487W",  "title": "Ubik",                             "author": "Philip K. Dick"},

    # ── Fantasy ───────────────────────────────────────────────────────────
    {"key": "/works/OL27516W",    "title": "The Hobbit",                       "author": "J.R.R. Tolkien"},
    {"key": "/works/OL27516W",    "title": "The Fellowship of the Ring",       "author": "J.R.R. Tolkien"},
    {"key": "/works/OL8479162W",  "title": "The Name of the Wind",             "author": "Patrick Rothfuss"},
    {"key": "/works/OL8480830W",  "title": "American Gods",                    "author": "Neil Gaiman"},
    {"key": "/works/OL8479488W",  "title": "Good Omens",                       "author": "Neil Gaiman"},
    {"key": "/works/OL8479489W",  "title": "Neverwhere",                       "author": "Neil Gaiman"},
    {"key": "/works/OL8479490W",  "title": "The Ocean at the End of the Lane",  "author": "Neil Gaiman"},
    {"key": "/works/OL8479491W",  "title": "Small Gods",                       "author": "Terry Pratchett"},
    {"key": "/works/OL8479492W",  "title": "Guards! Guards!",                  "author": "Terry Pratchett"},
    {"key": "/works/OL8479493W",  "title": "Night Watch",                      "author": "Terry Pratchett"},
    {"key": "/works/OL8479494W",  "title": "The Way of Kings",                 "author": "Brandon Sanderson"},
    {"key": "/works/OL8479495W",  "title": "Mistborn",                         "author": "Brandon Sanderson"},
    {"key": "/works/OL8479496W",  "title": "The Final Empire",                 "author": "Brandon Sanderson"},
    {"key": "/works/OL8479497W",  "title": "A Game of Thrones",                "author": "George R.R. Martin"},
    {"key": "/works/OL8479498W",  "title": "A Clash of Kings",                 "author": "George R.R. Martin"},
    {"key": "/works/OL8479499W",  "title": "Assassin's Apprentice",            "author": "Robin Hobb"},
    {"key": "/works/OL8479500W",  "title": "The Blade Itself",                 "author": "Joe Abercrombie"},
    {"key": "/works/OL8479501W",  "title": "The Lies of Locke Lamora",         "author": "Scott Lynch"},
    {"key": "/works/OL8479502W",  "title": "The Priory of the Orange Tree",    "author": "Samantha Shannon"},
    {"key": "/works/OL21176162W", "title": "Fourth Wing",                      "author": "Rebecca Yarros"},
    {"key": "/works/OL8479503W",  "title": "Iron Flame",                       "author": "Rebecca Yarros"},
    {"key": "/works/OL45804W",    "title": "Fantastic Mr Fox",                 "author": "Roald Dahl"},
    {"key": "/works/OL8479504W",  "title": "The BFG",                          "author": "Roald Dahl"},
    {"key": "/works/OL8479505W",  "title": "Matilda",                          "author": "Roald Dahl"},

    # ── Mystery & Thriller ────────────────────────────────────────────────
    {"key": "/works/OL47096W",    "title": "And Then There Were None",          "author": "Agatha Christie"},
    {"key": "/works/OL8479506W",  "title": "Murder on the Orient Express",     "author": "Agatha Christie"},
    {"key": "/works/OL8479507W",  "title": "The Murder of Roger Ackroyd",      "author": "Agatha Christie"},
    {"key": "/works/OL8479508W",  "title": "Rebecca",                          "author": "Daphne du Maurier"},
    {"key": "/works/OL8479509W",  "title": "Jamaica Inn",                      "author": "Daphne du Maurier"},
    {"key": "/works/OL15129138W", "title": "Gone Girl",                        "author": "Gillian Flynn"},
    {"key": "/works/OL8479510W",  "title": "Dark Places",                      "author": "Gillian Flynn"},
    {"key": "/works/OL8479511W",  "title": "Sharp Objects",                    "author": "Gillian Flynn"},
    {"key": "/works/OL15533385W", "title": "The Girl with the Dragon Tattoo",  "author": "Stieg Larsson"},
    {"key": "/works/OL8479512W",  "title": "The Girl Who Played with Fire",    "author": "Stieg Larsson"},
    {"key": "/works/OL8479513W",  "title": "In the Woods",                     "author": "Tana French"},
    {"key": "/works/OL8479514W",  "title": "The Likeness",                     "author": "Tana French"},
    {"key": "/works/OL8479515W",  "title": "The Secret Place",                 "author": "Tana French"},
    {"key": "/works/OL8479516W",  "title": "The Spy Who Came in from the Cold","author": "John le Carré"},
    {"key": "/works/OL8479517W",  "title": "Tinker Tailor Soldier Spy",        "author": "John le Carré"},
    {"key": "/works/OL8479518W",  "title": "The Night Manager",                "author": "John le Carré"},
    {"key": "/works/OL8479519W",  "title": "The Woman in the Window",          "author": "A.J. Finn"},
    {"key": "/works/OL8479520W",  "title": "The Silent Patient",               "author": "Alex Michaelides"},
    {"key": "/works/OL8479521W",  "title": "The Maidens",                      "author": "Alex Michaelides"},
    {"key": "/works/OL8479522W",  "title": "The Last House on Needles Lane",   "author": "Stuart Turton"},
    {"key": "/works/OL8479523W",  "title": "The 7½ Deaths of Evelyn Hardcastle","author": "Stuart Turton"},
    {"key": "/works/OL19631W",    "title": "In Cold Blood",                    "author": "Truman Capote"},
    {"key": "/works/OL17860591W", "title": "The Da Vinci Code",                "author": "Dan Brown"},
    {"key": "/works/OL8479524W",  "title": "Inferno",                          "author": "Dan Brown"},
    {"key": "/works/OL8479525W",  "title": "The Girl on the Train",            "author": "Paula Hawkins"},
    {"key": "/works/OL8479526W",  "title": "Into the Water",                   "author": "Paula Hawkins"},
    {"key": "/works/OL8479527W",  "title": "The Thursday Murder Club",         "author": "Richard Osman"},
    {"key": "/works/OL8479528W",  "title": "One by One",                       "author": "Ruth Ware"},
    {"key": "/works/OL8479529W",  "title": "The Turn of the Key",              "author": "Ruth Ware"},
    {"key": "/works/OL8479530W",  "title": "Olga Dies Dreaming",               "author": "Xochitl Gonzalez"},

    # ── Horror ────────────────────────────────────────────────────────────
    {"key": "/works/OL8479531W",  "title": "The Shining",                      "author": "Stephen King"},
    {"key": "/works/OL8479532W",  "title": "It",                               "author": "Stephen King"},
    {"key": "/works/OL8479533W",  "title": "Carrie",                           "author": "Stephen King"},
    {"key": "/works/OL8479534W",  "title": "Pet Sematary",                     "author": "Stephen King"},
    {"key": "/works/OL8479535W",  "title": "Misery",                           "author": "Stephen King"},
    {"key": "/works/OL21176160W", "title": "Holly",                            "author": "Stephen King"},
    {"key": "/works/OL8479536W",  "title": "We Have Always Lived in the Castle","author": "Shirley Jackson"},
    {"key": "/works/OL8479537W",  "title": "The Haunting of Hill House",       "author": "Shirley Jackson"},
    {"key": "/works/OL8479538W",  "title": "Mexican Gothic",                   "author": "Silvia Moreno-Garcia"},
    {"key": "/works/OL8479539W",  "title": "Plain Bad Heroines",               "author": "Emily M. Danforth"},
    {"key": "/works/OL8479540W",  "title": "The Troop",                        "author": "Nick Cutter"},

    # ── Wereldliteratuur (Engels vertaald) ───────────────────────────────
    {"key": "/works/OL16324W",    "title": "One Hundred Years of Solitude",    "author": "Gabriel García Márquez"},
    {"key": "/works/OL8479541W",  "title": "Love in the Time of Cholera",      "author": "Gabriel García Márquez"},
    {"key": "/works/OL8479302W",  "title": "The Alchemist",                    "author": "Paulo Coelho"},
    {"key": "/works/OL21508W",    "title": "Crime and Punishment",             "author": "Fyodor Dostoyevsky"},
    {"key": "/works/OL8478999W",  "title": "The Brothers Karamazov",           "author": "Fyodor Dostoyevsky"},
    {"key": "/works/OL8479542W",  "title": "The Idiot",                        "author": "Fyodor Dostoyevsky"},
    {"key": "/works/OL8479543W",  "title": "War and Peace",                    "author": "Leo Tolstoy"},
    {"key": "/works/OL8479544W",  "title": "Anna Karenina",                    "author": "Leo Tolstoy"},
    {"key": "/works/OL20613872W", "title": "The Stranger",                     "author": "Albert Camus"},
    {"key": "/works/OL8479545W",  "title": "The Plague",                       "author": "Albert Camus"},
    {"key": "/works/OL8449027W",  "title": "Nausea",                           "author": "Jean-Paul Sartre"},
    {"key": "/works/OL17330574W", "title": "The Trial",                        "author": "Franz Kafka"},
    {"key": "/works/OL8479301W",  "title": "The Metamorphosis",                "author": "Franz Kafka"},
    {"key": "/works/OL8479546W",  "title": "The Castle",                       "author": "Franz Kafka"},
    {"key": "/works/OL17337938W", "title": "Siddhartha",                       "author": "Hermann Hesse"},
    {"key": "/works/OL8479305W",  "title": "Steppenwolf",                      "author": "Hermann Hesse"},
    {"key": "/works/OL8479308W",  "title": "The Master and Margarita",         "author": "Mikhail Bulgakov"},
    {"key": "/works/OL8479310W",  "title": "Perfume",                          "author": "Patrick Süskind"},
    {"key": "/works/OL17336041W", "title": "The Wind-Up Bird Chronicle",       "author": "Haruki Murakami"},
    {"key": "/works/OL8479311W",  "title": "Norwegian Wood",                   "author": "Haruki Murakami"},
    {"key": "/works/OL8479312W",  "title": "Kafka on the Shore",               "author": "Haruki Murakami"},
    {"key": "/works/OL8479547W",  "title": "1Q84",                             "author": "Haruki Murakami"},
    {"key": "/works/OL8479548W",  "title": "The Unbearable Lightness of Being","author": "Milan Kundera"},
    {"key": "/works/OL8479549W",  "title": "The Book of Laughter and Forgetting","author": "Milan Kundera"},
    {"key": "/works/OL8479550W",  "title": "The Tin Drum",                     "author": "Günter Grass"},
    {"key": "/works/OL8479551W",  "title": "Hunger",                           "author": "Knut Hamsun"},
    {"key": "/works/OL8479552W",  "title": "Narcissus and Goldmund",           "author": "Hermann Hesse"},
    {"key": "/works/OL8479553W",  "title": "The Reader",                       "author": "Bernhard Schlink"},
    {"key": "/works/OL8479554W",  "title": "Austerlitz",                       "author": "W.G. Sebald"},
    {"key": "/works/OL8479555W",  "title": "The Rings of Saturn",              "author": "W.G. Sebald"},
    {"key": "/works/OL8479556W",  "title": "My Brilliant Friend",              "author": "Elena Ferrante"},
    {"key": "/works/OL8479557W",  "title": "The Story of a New Name",          "author": "Elena Ferrante"},
    {"key": "/works/OL8479558W",  "title": "Those Who Leave and Those Who Stay","author": "Elena Ferrante"},
    {"key": "/works/OL8479559W",  "title": "The Story of the Lost Child",      "author": "Elena Ferrante"},
    {"key": "/works/OL8479313W",  "title": "Snow Country",                     "author": "Yasunari Kawabata"},
    {"key": "/works/OL8479560W",  "title": "The Sound of Waves",               "author": "Yukio Mishima"},
    {"key": "/works/OL8479561W",  "title": "The Temple of the Golden Pavilion","author": "Yukio Mishima"},
    {"key": "/works/OL8479562W",  "title": "The Makioka Sisters",              "author": "Jun'ichirō Tanizaki"},
    {"key": "/works/OL8479563W",  "title": "Silence",                          "author": "Shūsaku Endō"},
    {"key": "/works/OL8479564W",  "title": "The Woman in the Dunes",           "author": "Kōbō Abe"},
    {"key": "/works/OL8479565W",  "title": "Convenience Store Woman",          "author": "Sayaka Murata"},
    {"key": "/works/OL8479566W",  "title": "Earthlings",                       "author": "Sayaka Murata"},
    {"key": "/works/OL8479567W",  "title": "Things Fall Apart",                "author": "Chinua Achebe"},
    {"key": "/works/OL8479568W",  "title": "Arrow of God",                     "author": "Chinua Achebe"},
    {"key": "/works/OL8479569W",  "title": "Season of Migration to the North", "author": "Tayeb Salih"},
    {"key": "/works/OL8479570W",  "title": "Half of a Yellow Sun",             "author": "Chimamanda Ngozi Adichie"},
    {"key": "/works/OL8479571W",  "title": "Purple Hibiscus",                  "author": "Chimamanda Ngozi Adichie"},
    {"key": "/works/OL8479572W",  "title": "Americanah",                       "author": "Chimamanda Ngozi Adichie"},
    {"key": "/works/OL8479573W",  "title": "Disgrace",                         "author": "J.M. Coetzee"},
    {"key": "/works/OL8479574W",  "title": "Waiting for the Barbarians",       "author": "J.M. Coetzee"},
    {"key": "/works/OL8479575W",  "title": "The God of Small Things",          "author": "Arundhati Roy"},
    {"key": "/works/OL8479576W",  "title": "A Fine Balance",                   "author": "Rohinton Mistry"},
    {"key": "/works/OL8479577W",  "title": "The White Tiger",                  "author": "Aravind Adiga"},

    # ── Young Adult ───────────────────────────────────────────────────────
    {"key": "/works/OL8479578W",  "title": "The Hunger Games",                 "author": "Suzanne Collins"},
    {"key": "/works/OL8479579W",  "title": "Catching Fire",                    "author": "Suzanne Collins"},
    {"key": "/works/OL8479580W",  "title": "Mockingjay",                       "author": "Suzanne Collins"},
    {"key": "/works/OL8479581W",  "title": "Divergent",                        "author": "Veronica Roth"},
    {"key": "/works/OL8479582W",  "title": "The Maze Runner",                  "author": "James Dashner"},
    {"key": "/works/OL8479583W",  "title": "The Fault in Our Stars",           "author": "John Green"},
    {"key": "/works/OL8479584W",  "title": "Looking for Alaska",               "author": "John Green"},
    {"key": "/works/OL8479585W",  "title": "An Abundance of Katherines",       "author": "John Green"},
    {"key": "/works/OL8479586W",  "title": "The Perks of Being a Wallflower",  "author": "Stephen Chbosky"},
    {"key": "/works/OL8479587W",  "title": "Speak",                            "author": "Laurie Halse Anderson"},
    {"key": "/works/OL8479588W",  "title": "The House on Mango Street",        "author": "Sandra Cisneros"},
    {"key": "/works/OL8479589W",  "title": "The Giver",                        "author": "Lois Lowry"},
    {"key": "/works/OL8479590W",  "title": "Six of Crows",                     "author": "Leigh Bardugo"},
    {"key": "/works/OL8479591W",  "title": "Shadow and Bone",                  "author": "Leigh Bardugo"},
    {"key": "/works/OL8479592W",  "title": "The Atlas Six",                    "author": "Olivie Blake"},
    {"key": "/works/OL8479593W",  "title": "A Court of Thorns and Roses",      "author": "Sarah J. Maas"},
    {"key": "/works/OL8479594W",  "title": "Throne of Glass",                  "author": "Sarah J. Maas"},
    {"key": "/works/OL8479595W",  "title": "Children of Blood and Bone",       "author": "Tomi Adeyemi"},

    # ── Narrative non-fictie & memoires ───────────────────────────────────
    {"key": "/works/OL8479387W",  "title": "Educated",                         "author": "Tara Westover"},
    {"key": "/works/OL8479441W",  "title": "Crying in H Mart",                 "author": "Michelle Zauner"},
    {"key": "/works/OL8479596W",  "title": "The Glass Castle",                 "author": "Jeannette Walls"},
    {"key": "/works/OL8479597W",  "title": "Wild",                             "author": "Cheryl Strayed"},
    {"key": "/works/OL8479598W",  "title": "Between the World and Me",         "author": "Ta-Nehisi Coates"},
    {"key": "/works/OL8479599W",  "title": "The Year of Magical Thinking",     "author": "Joan Didion"},
    {"key": "/works/OL8479600W",  "title": "When Breath Becomes Air",          "author": "Paul Kalanithi"},
    {"key": "/works/OL8479601W",  "title": "Being Mortal",                     "author": "Atul Gawande"},
    {"key": "/works/OL8479602W",  "title": "The Immortal Life of Henrietta Lacks","author": "Rebecca Skloot"},
    {"key": "/works/OL8479603W",  "title": "Sapiens",                          "author": "Yuval Noah Harari"},
    {"key": "/works/OL8479604W",  "title": "Homo Deus",                        "author": "Yuval Noah Harari"},
    {"key": "/works/OL8479605W",  "title": "Born a Crime",                     "author": "Trevor Noah"},
    {"key": "/works/OL8479606W",  "title": "I Know Why the Caged Bird Sings",  "author": "Maya Angelou"},
    {"key": "/works/OL8479607W",  "title": "Just Kids",                        "author": "Patti Smith"},
    {"key": "/works/OL8479608W",  "title": "The Autobiography of Malcolm X",   "author": "Malcolm X"},
]

# Dedupliceer op key
seen = set()
UNIQUE_BOOKS = []
for b in SEED_BOOKS:
    if b["key"] not in seen:
        seen.add(b["key"])
        UNIQUE_BOOKS.append(b)


import re as _re

def _parse_year(value) -> int | None:
    if isinstance(value, int):
        return value if 1000 < value < 2100 else None
    if isinstance(value, str):
        m = _re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", value)
        return int(m.group(1)) if m else None
    return None


async def fetch_description(client: httpx.AsyncClient, work_key: str) -> tuple[str, list[str], str | None, str | None, int | None]:
    """Haalt beschrijving, subjects, cover_id, ol_title en year op voor een work-key."""
    url = f"https://openlibrary.org{work_key}.json"
    try:
        r = await client.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        desc = data.get("description", "")
        if isinstance(desc, dict):
            desc = desc.get("value", "")
        subjects = data.get("subjects", [])[:10]
        covers   = data.get("covers", [])
        cover_id = covers[0] if covers else None
        ol_title = data.get("title")
        year     = _parse_year(data.get("first_publish_date"))

        # Jaar via search-API als het werk het niet heeft
        if not year:
            ol_id = work_key.split("/")[-1]
            sr = await client.get(
                "https://openlibrary.org/search.json",
                params={"q": f"key:{work_key}", "fields": "first_publish_year", "limit": 1},
                timeout=10,
            )
            if sr.is_success:
                docs = sr.json().get("docs", [])
                if docs:
                    year = _parse_year(docs[0].get("first_publish_year"))

        return desc or "", subjects, cover_id, ol_title, year
    except Exception as e:
        print(f"  ⚠  Fout bij {work_key}: {e}")
        return "", [], None, None, None


async def build():
    print(f"⏳ Index bouwen voor {len(UNIQUE_BOOKS)} boeken…")
    get_model()

    books_meta = []
    topic_vectors = []
    style_vectors = []

    async with httpx.AsyncClient() as client:
        for i, book in enumerate(UNIQUE_BOOKS):
            print(f"  [{i+1}/{len(UNIQUE_BOOKS)}] {book['title']}")
            desc, subjects, cover_id, ol_title, year = await fetch_description(client, book["key"])

            # Gebruik de OL-titel zodat link en titel altijd overeenkomen
            title = ol_title or book["title"]

            if not desc:
                desc = f"{title} by {book['author']}. {' '.join(subjects)}"

            vecs = embed_book(desc, subjects)
            topic_vectors.append(vecs["topic"])
            style_vectors.append(vecs["style"])

            books_meta.append({
                "title": title,
                "author": book["author"],
                "description": desc[:500],
                "subjects": subjects,
                "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None,
                "ol_key": book["key"],
                "year": year,
            })

    dim = topic_vectors[0].shape[0]
    topic_matrix = np.stack(topic_vectors).astype(np.float32)
    style_matrix = np.stack(style_vectors).astype(np.float32)

    topic_index = faiss.IndexFlatIP(dim)
    topic_index.add(topic_matrix)
    style_index = faiss.IndexFlatIP(dim)
    style_index.add(style_matrix)

    faiss.write_index(topic_index, os.path.join(DATA_DIR, "faiss_topic.index"))
    faiss.write_index(style_index, os.path.join(DATA_DIR, "faiss_style.index"))
    with open(os.path.join(DATA_DIR, "books.json"), "w") as f:
        json.dump(books_meta, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Index gebouwd met {len(books_meta)} boeken.")
    print(f"   Opgeslagen in: {DATA_DIR}/")


if __name__ == "__main__":
    asyncio.run(build())
