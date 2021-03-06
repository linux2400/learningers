# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import models
from commons.coding import classproperty
from model_utils.models import TimeStampedModel
from model_utils.managers import InheritanceManager
from forkit.models import ForkableModel
from django_languages.fields import LanguageField
from south.modelsinspector import add_introspection_rules
from django.utils.translation import get_language
from django.utils.translation import ugettext as _
from django.utils.translation import ugettext_lazy as __
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from commons.signals import receiver_subclasses
import geopy
import reversion
import re # regular expressions
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.conf import settings
from imaging.models import Image
from django.template.loader import render_to_string

# for GeoLocation
from django.contrib.gis.db.models import GeoManager, PointField
from geopy import geocoders
from django.contrib.gis.geos import fromstr
from django.http.response import Http404

class ResourceLanguage(models.Model):
    """
    Une langue utilisée dans une ou plusieurs resources répertoriées
    """
    code = LanguageField()
    @staticmethod
    def get_mycurrent():
        "Retourne la langue actuellement utilisée pour la session en cours"
        code = get_language().split('-')[0]
        language,created = ResourceLanguage.objects.get_or_create(code=code)
        return language        
    def __unicode__(self):
        "Retourne le nom de la langue"
        return self.get_code_display()
    
add_introspection_rules([], ["^django_languages\.fields\.LanguageField"])

class Comment(TimeStampedModel):
    """
    A comment concerning a resource.
    """
    resource = models.ForeignKey('catalog.Resource',verbose_name=_(u'Ressource'),help_text=_(u"La ressource concernée"),related_name='comments')
    text = models.TextField(verbose_name=_(u'Contenu'), blank=True)
    COLOUR_CHOICES = (
        (0, u'Vert'),
        (1, u'Orange'),
        (2, u'Rouge'),
    ) 

    COLOUR_RGB = ('#AAFFAA','#FFDDAA','#FFAAAA')

    colour = models.IntegerField(choices=COLOUR_CHOICES,verbose_name=_(u'Couleur'),help_text=_(u"Vert=OK,Orange=Avis mitigé,Rouge=Demande de veto"))
    CATEGORY_CHOICES = (
        (0, u"Pas d'enfermement"),
        (1, u"Pas d'autorité"),
        (2, u"Respect de l'intimité"),
        (3, u"Respect de l'information")
    )
    category = models.IntegerField(choices=CATEGORY_CHOICES)
    author = models.ForeignKey(User,verbose_name=_(u'AuteurE'))
    def get_colour_rgb(self):
        return self.COLOUR_RGB[self.colour]
    
class Resource(TimeStampedModel,ForkableModel):
    """
    Modèle abstrait de base pour les resources répertoriées dans le catalogue.
    
    Les modèles correspondant aux différents types de resources dérivent de celui-ci.
    """
    # Resource id
    resource_id = models.AutoField(primary_key=True)
    # Resource name
    name = models.CharField(max_length=200, verbose_name=__('Titre'), help_text=__(u'Le nom de la ressource dans le répertoire'))
    # Resource description
    description = models.CharField(max_length=1000, verbose_name=__('Description'),blank=True, help_text=__(u'Une brève description du contenu de la ressource'))
    # Resource parent
    parent = models.ForeignKey('catalog.Way',verbose_name=__('Parcours'),blank=True,null=True,default=None,related_name='children', help_text=__('Le parcours dont cette ressource fait partie'))
    # Resource slug
    slug = models.CharField(max_length=100,editable=False)  
    # Languages used in this resource
    languages = models.ManyToManyField(ResourceLanguage,editable=False, help_text=__(u'Les langues à maîtriser pour comprendre cette ressource'))
    # Other entries related to this resource
    see_also = models.ManyToManyField('catalog.Resource',verbose_name=__('Voir aussi'),blank=True,null=True,default=None, help_text=__(u"D'autres resources liées à celle-ci"))
    # Is this resource private or public ?
    public = models.BooleanField(editable=False,default=True)
    # A picture representing this resource 
    avatar = models.ForeignKey(Image,blank=True,default=None,null=True,verbose_name=__(u'Avatar'), help_text=__(u"Une image représentant cette ressource"))
    # To manage inheritance
    objects = InheritanceManager()    
    
    def save(self,*args,**kwargs):
        if not self.pk:
            if not self.slug:
                self.slug = slugify(self.name)
        super(Resource, self).save(*args,**kwargs)
    # both slug and name should always be unique for a given resource type with a given parent
    def validate_unique(self,exclude=None):
        if self.__class__.objects.exclude(pk=self.pk).filter(slug=self.slug,parent=self.parent).exists():
            raise ValidationError({'slug':_(u'Une entrée du même slug et du même type existe déjà dans ce parcours.'),})
        if self.__class__.objects.exclude(pk=self.pk).filter(name=self.name,parent=self.parent).exists():
            raise ValidationError({'name':_(u'Une entrée du même nom et du même type existe déjà dans ce parcours.'),})
        super(Resource, self).validate_unique(exclude=exclude)
    # Stringify
    def __unicode__(self):  # Python 3: def __str__(self):
        return self.name
    def get_absolute_url(self):
        if self.parent:
            #print "toto1 : %s" % self.resource_type
            return self.parent.get_absolute_url() + self.resource_type + '/' + self.slug + '/'
        else:
            raise Http404
    def preview(self):
        "return HTML code to display a small preview of this resource"
        print('hi bitch')
        return render_to_string('catalog/' + self.resource_type + '/info.html', { 'resource' : self })

re_latitude_longitude = re.compile(r'([0-9.]+),([0-9.])+')
            
class GeoLocation(models.Model):
    """
    La localisation géographique d'une ressource
    """
    # Entry associated address
    address = models.CharField(max_length=200,verbose_name=__('Adresse'),help_text=__("L'adresse postale du lieu"))
    # Entry associated location
    location = PointField(editable=False,verbose_name=__(u'Coordonnées'),help_text=__(u"Les coordonnées GPS du lieu"))
    # manager
    objects = GeoManager()
    def save(self,*args,**kwargs):
        g = geocoders.Nominatim() # this should be changed to openstreetmap
        try:
            place, (lat,lng) = g.geocode(self.address)
            self.location = fromstr("POINT(%s %s)" % (lng, lat))
            self.address = place
        except geopy.exc.GeocoderServiceError:
            self.location = fromstr("POINT(0 0)")
            print "WARNING: could not geocode %s !!" % self.address            
        super(GeoLocation, self).save(*args,**kwargs)
    @staticmethod
    def make_from_slug(slug):
        g = geocoders.Nominatim() # this should be changed to openstreetmap
        m = re_latitude_longitude.match(slug)
        lat = m.group(1)
        lng = m.group(2)
        location = fromstr("POINT(%s %s)" % (lng, lat))
        address = g.reverse("%s, %s" %(lat,lng),exactly_one=1)
        return GeoLocation(address=address,location=location)
    @property
    def slug(self):
        return "%s, %s" %(self.location.get_x(),self.location.get_y())           
    def __unicode__(self):
        return self.address

available_resource_models = {}
available_search_engines = {}

def register_resource(resource_model):
    resource_type = resource_model.__name__.lower()
    setattr(resource_model,'resource_type',resource_type)
    setattr(resource_model,'user_friendly_type',resource_model._meta.verbose_name.title())
    available_resource_models[resource_type] = resource_model
    # Register external search engines if any are found
    if hasattr(resource_model,'ExternalSearch'):
        resource_model.ExternalSearch.name = resource_type
        resource_model.ExternalSearch.user_friendly_name = resource_model._meta.verbose_name
        available_search_engines[resource_type] = resource_model.ExternalSearch

@receiver_subclasses(post_save, Resource,'resource-language')
def resource_post_save(sender,**kwargs):
    if kwargs['instance'].languages.count() == 0:
        kwargs['instance'].languages.add(ResourceLanguage.get_mycurrent())
        kwargs['instance'].save() 
           
# register for version control
reversion.register(Resource)

available_annotation_contents = {}

def register_annotation_content(content_model):
    content_type = content_model.__name__.lower()
    setattr(content_model,'content_type',content_type)
    setattr(content_model,'user_friendly_type',content_model._meta.verbose_name.title())
    available_annotation_contents[content_type] = content_model
    
available_annotation_ranges = {}

def register_annotation_range(range_model):
    range_type = range_model.__name__.lower()
    setattr(range_model,'range_type',range_type)
    setattr(range_model,'user_friendly_type',range_model._meta.verbose_name.title())
    available_annotation_ranges[range_type] = range_model

