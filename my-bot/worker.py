import discord
import asyncio
import re
import requests
from html import unescape

rbold = re.compile(r"'''")
rparens = re.compile(r" \(.+?\)")
rtags = re.compile(r"<.+?>")
rlinks = re.compile(r"\[\[(.*?)(\|)?(?(2)(.*?))\]\]")
rformatting = re.compile(r"{.+?}}")
rctrlchars = re.compile(r"\\.")
#rfirstheader = re.compile(r"=.*")
rfirstpbreak = re.compile(r"\\n\\n.*")
rredirect = re.compile(r"\[\[(.+?)\]\]")

rtitle = re.compile(r'"title":"(.+?)",')
rgif = re.compile(r"File[^F]+?\.gif")
rimage = re.compile(r"File[^F]+?\.png")
rfileurl = re.compile(r'"url":"(.+?)"')

def regex(txt):
    txt = rfirstpbreak.sub('', txt) # exchange with rfirstheader.sub() below for entire first section to be preserved
    txt = rbold.sub('**', txt)
    txt = rparens.sub('', txt)
    txt = rtags.sub('', txt)
    txt = rlinks.sub(lambda m: m.group(3) if m.group(3) else m.group(1), txt)
    txt = rformatting.sub('', txt)
    txt = rctrlchars.sub('', txt)
#   txt = rfirstheader.sub('', txt)
    return txt

client = discord.Client()

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')

@client.event
async def on_message(message):
    em = discord.Embed()
    if message.content.startswith("!wiki"):
        query = message.content[6:]
        
        with requests.Session() as rqst:
            images = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=images&format=json&titles=" + query).text
            pgimg = rgif.search(images).group(0)
            if not pgimg:
                pgimg = min(rimage.findall(images), key = len)
            if pgimg:
                images = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=imageinfo&iiprop=url&format=json&titles=" + pgimg).text
                pgimg = rfileurl.search(images).group(1)
                em.set_image(url=pgimg)
            
            data = rqst.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
            if '#REDIRECT' in data:
                em.set_footer(text='(redirected from "' + query + '")')
                query = rredirect.search(data).group(1)
                data = requests.get("http://conwaylife.com/w/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + query).text
        
        if '"-1":{' in data:
            await client.send_message(message.channel, 'Page `' + query + '` does not exist.')
        else:
            pgtitle = rtitle.search(data).group(1)
            desc = unescape(regex(data))
            
            em.title = pgtitle
            em.url = "http://conwaylife.com/wiki/" + query.replace(" ", "_")
            em.description = desc
            em.color = 0x680000
            
            await client.send_message(message.channel, embed=em)

client.run('MzU5MDY3NjM4MjE2Nzg1OTIw.DKBnUw.MJm4R_Zz6hCI3TPLT05wsdn6Mgs')
