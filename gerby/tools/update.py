import re
import os
import os.path
import logging, sys
import pickle
import pybtex.database

from gerby.database import *
import gerby.config as config


logging.basicConfig(stream=sys.stdout)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# create database if it doesn't exist already
if not os.path.isfile(config.DATABASE):
  for model in [Tag, Proof, Extra, Comment]:
    model.create_table()
  log.info("Created database")


# the information on disk
files = [f for f in os.listdir(config.PATH) if os.path.isfile(os.path.join(config.PATH, f)) and f != "index"] # index is always created

tagFiles = [filename for filename in files if filename.endswith(".tag")]
proofFiles = [filename for filename in files if filename.endswith(".proof")]
footnoteFiles = [filename for filename in files if filename.endswith(".footnote")]
# TODO make sure that plasTeX copies the used .bib files to the output folder
bibliographyFiles = [filename for filename in files if filename.endswith(".bib")]

extras = ("slogan", "history", "reference")
extraFiles = [filename for filename in files if filename.endswith(extras)]

context = pickle.load(open(os.path.join(config.PAUX), "rb"))

with open(config.TAGS) as f:
  tags = f.readlines()
  tags = [line.strip() for line in tags if not line.startswith("#")]
  tags = dict([line.split(",") for line in tags if "," in line])
  labels = {item: key for key, item in tags.items()}

# import tags
"""
log.info("Importing tags")
for filename in tagFiles:
  with open(os.path.join(config.PATH, filename)) as f:
    value = f.read()

  filename = filename[:-4]
  pieces = filename.split("-")

  tag, created = Tag.get_or_create(tag=pieces[2])

  if created:
    log.info("  Created tag %s", pieces[2])
  else:
    if tag.label != "-".join(pieces[3:]):
      log.info("  Tag %s: label has changed", tag.tag)
    if tag.html != value:
      log.info("  Tag %s: content has changed", tag.tag)
    if tag.type != pieces[0]:
      log.info("  Tag %s: type has changed", tag.tag)

  tag.label = "-".join(pieces[3:])
  tag.ref = pieces[1]
  tag.type = pieces[0]
  tag.html = value

  tag.save()


# post-processing tags
for entity in list(Tag.select()) + list(Proof.select()):
  regex = re.compile(r'\\ref\{([0-9A-Za-z\-]+)\}')
  for label in regex.findall(entity.html):
    try:
      reference = Tag.get(Tag.label == label)
      entity.html = entity.html.replace("\\ref{" + label + "}", reference.tag)

    # if the label isn't recognised (which happens on 02BZ in the Stacks project, for a very silly reason), just ignore
    except:
      pass

  entity.save()


# import proofs
log.info("Importing proofs")
for filename in proofFiles:
  with open(os.path.join(config.PATH, filename)) as f:
    value = f.read()

  filename = filename[:-6]
  pieces = filename.split("-")

  proof, created = Proof.get_or_create(tag=pieces[0], number=int(pieces[1]))

  if created:
    log.info("  Tag %s: created proof #%s", proof.tag.tag, proof.number)
  else:
    if proof.html != value:
      log.info("Tag %s: proof #%s has changed", proof.tag.tag, pieces[1])

  proof.html = value

  # looking for stray \ref's
  regex = re.compile(r'\\ref\{([0-9A-Za-z\-]+)\}')
  for label in regex.findall(proof.html):
    try:
      reference = Tag.get(Tag.label == label)
      proof.html = proof.html.replace("\\ref{" + label + "}", reference.tag)

    # if the label isn't recognised (which happens on 02BZ in the Stacks project, for a very silly reason), just ignore
    except:
      pass

  proof.save()


# import footnotes
log.info("Importing footnotes")
if Footnote.table_exists():
  Footnote.drop_table()
Footnote.create_table()

for filename in footnoteFiles:
  with open(os.path.join(config.PATH, filename)) as f:
    value = f.read()

  label = filename.split(".")[0]

  Footnote.create(label=label, html=value)

# create search table
log.info("Populating the search table")
if TagSearch.table_exists():
  TagSearch.drop_table()
TagSearch.create_table()

for tag in Tag.select():
  proofs = Proof.select().where(Proof.tag == tag.tag).order_by(Proof.number)

  TagSearch.insert({
    TagSearch.tag: tag.tag,
    TagSearch.html: tag.html,
    TagSearch.full: tag.html + "".join([proof.html for proof in proofs]), # TODO collate with proofs
    }).execute()

# link chapters to parts
log.info("Assigning chapters to parts")
if Part.table_exists():
  Part.drop_table()
Part.create_table()

with open(os.path.join(config.PATH, "parts.json")) as f:
  parts = json.load(f)
  for part in parts:
    for chapter in parts[part]:
      Part.create(part=Tag.get(Tag.type == "part", Tag.ref == part), chapter=Tag.get(Tag.type == "chapter", Tag.ref == chapter))


# check (in)activity of tags
log.info("Checking inactivity")
for tag in Tag.select():
  if tag.tag not in tags:
    log.info("  Tag %s became inactive", tag.tag)
    tag.active = False
  else:
    if tag.label != tags[tag.tag]:
      log.error("  Labels for tag %s differ from tags file to database:\n  - %s\n  - %s", tag.tag, tags[tag.tag], tag.label)
    else:
      tag.active = True

  tag.save()


# create dependency data
log.info("Creating dependency data")
if Dependency.table_exists():
  Dependency.drop_table()
Dependency.create_table()

for proof in Proof.select():
  regex = re.compile(r'\"/tag/([0-9A-Z]{4})\"')
  with db.atomic():
    dependencies = regex.findall(proof.html)

    if len(dependencies) > 0:
      Dependency.insert_many([{"tag": proof.tag.tag, "to": to} for to in dependencies]).execute()


# import history, slogans, etc
log.info("Importing history, slogans, etc.")
for filename in extraFiles:
  with open(os.path.join(config.PATH, filename)) as f:
    value = f.read()

  pieces = filename.split(".")

  extra, created = Extra.get_or_create(tag=pieces[0], type=pieces[1])

  if created:
    log.info("  Tag %s: added a %s", extra.tag.tag, pieces[1])
  else:
    if extra.html != value:
      log.info("  Tag %s: %s has changed", extra.tag.tag, pieces[1])

  extra.html = value
  extra.save()


# import names of labels
log.info("Importing names of tags")
names = list()

for key, item in context["Gerby"].items():
  if "title" in item and key in labels:
    names.append({"tag" : labels[key], "name" : item["title"]})

for entry in names:
  Tag.update(name=entry["name"]).where(Tag.tag == entry["tag"]).execute()

# import bibliography
log.info("Importing bibliography")
if BibliographyEntry.table_exists():
  BibliographyEntry.drop_table()
BibliographyEntry.create_table()

if BibliographyField.table_exists():
  BibliographyField.drop_table()
BibliographyField.create_table()

for bibliographyFile in bibliographyFiles:
  bibtex = pybtex.database.parse_file(os.path.join(config.PATH, bibliographyFile))

  for key in bibtex.entries:
    entry = bibtex.entries[key]

    data = pybtex.database.BibliographyData({key: entry}) # we create a new object to output a single entry
    BibliographyEntry.create(entrytype = entry.type, key = entry.key, code = data.to_string("bibtex"))

    for field in list(entry.rich_fields.keys()) + entry.persons.keys():
      value = entry.rich_fields[field].render_as("html")

      BibliographyField.create(key = entry.key, field = field.lower(), value = value)

# managing citations
if Citation.table_exists():
  Citation.drop_table()
Citation.create_table()

for tag in Tag.select():
  regex = re.compile(r'\"/bibliography/([0-9A-Za-z\-]+)\"')

  with db.atomic():
    citations = regex.findall(tag.html)
    citations = list(set(citations)) # make sure citations are inserted only once

    if len(citations) > 0:
      Citation.insert_many([{"tag": tag.tag, "key": citation} for citation in citations]).execute()
"""




# managing history
Change.drop_table() # TODO always drop Change table?
if not Change.table_exists():
  Change.create_table()

if not Commit.table_exists():
  Commit.create_table()

# TODO make stacks-history importable? or rather, make Gerby.database importable in stacks-history, and deal with updating the database over there?
class env_with_proof:
  def __init__(self, name, type, label, tag, b, e, text, bp, ep, proof):
    self.name = name
    self.type = type
    self.label = label
    self.tag = tag
    self.b = b
    self.e = e
    self.text = text
    self.bp = bp
    self.ep = ep
    self.proof = proof

class env_without_proof:
  def __init__(self, name, type, label, tag, b, e, text):
    self.name = name
    self.type = type
    self.label = label
    self.tag = tag
    self.b = b
    self.e = e
    self.text = text

class env_history:
  def __init__(self, commit, env, commits, envs):
    self.commit = commit
    self.env = env
    self.commits = commits
    self.envs = envs

class history:
  def __init__(self, commit, env_histories, commits):
    self.commit = commit
    self.env_histories = env_histories
    self.commits = commits

def createChange(commit, tag, change, action, begin, end):
  if not Tag.select().where(Tag.tag == tag).exists():
    log.error("  Tag %s does not exist, but it appears in the history", tag)
    return

  if not Commit.select().where(Commit.hash == commit).exists():
    log.error("  Commit %s does not exist, but it appears in the history", commit) # TODO is it possible for this to happen? It seems to happen on tag 058V, and commit 8a1f3c3754c4470069f73bd5a07e1edc8c0bf04b, which is also the filename I'm using, so maybe that's why
    return

  Change.create(tag=tag,
                hash=commit,
                filename=change.name,
                action=action,
                label=change.label,
                begin=begin,
                end=end)


# copy a recent history file to this directory for now TODO make this better
with open("8a1f3c3754c4470069f73bd5a07e1edc8c0bf04b", "rb") as f:
  history = pickle.load(f)

  for commit in history.commits:
    if not Commit.select().where(Commit.hash == commit).exists():
      print(commit)
      # TODO get commit info
      Commit.create(hash=commit)

  for environment in history.env_histories:
    # if no tag is present the environment isn't tagged yet, so we can ignore it
    if environment.env.tag == "":
      continue

    label = ""
    tag = ""
    name = ""
    text = ""
    proof = ""
    lines = [0, 0] # TODO this is not dealt with at the moment?

    print("Considering the history of tag %s" % environment.env.tag)
    for commit, change in zip(environment.commits, environment.envs):
      #print("  Looking at commit %s" % commit)
      action = ""

      # a tag was assigned
      if change.tag != tag and change.tag != "":
        #print("    Tag was assigned")
        createChange(commit, environment.env.tag, change, "tag", change.b, change.e)
        tag = change.tag

      # label was changed
      if change.label != label:
        # if name = "" then it's actually a statement creation
        if name != "":
          #print("    Label was changed")
          createChange(commit, environment.env.tag, change, "label", change.b, change.e)

        label = change.label

      # filename was changed (can also mean statement was created)
      if change.name != name:
        if name == "":
          #print("    Statement was created")
          createChange(commit, environment.env.tag, change, "creation", change.b, change.e)
        else:
          #print("    Tag moved files")
          createChange(commit, environment.env.tag, change, "move file", change.b, change.e)

        name = change.name

      # change in text of statement
      if change.text != text:
        if text != "": # if text == "" it's actually a creation
          #print("    Statement was modified")
          createChange(commit, environment.env.tag, change, "statement", change.b, change.e)

        text = change.text

      # change in text of proof
      if hasattr(change, "proof"):
        if proof != "": # TODO logic in original code is weird here, please check
          #print("    Proof was changed")
          createChange(commit, environment.env.tag, change, "proof", change.bp, change.ep)

        proof = change.proof
