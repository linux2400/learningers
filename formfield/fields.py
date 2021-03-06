#!/usr/bin/env python
# -*- coding: utf-8 -*-
from django.db import models
from django import forms
from django.core.serializers.json import DjangoJSONEncoder
import json
from django.template.defaultfilters import striptags
from django.core.exceptions import ValidationError
from django.forms.models import ModelForm
from .widgets import FormFieldWidget
from django.core.files.uploadedfile import UploadedFile


class JSONField(models.TextField):
    """
    JSONField is a generic textfield that serializes/unserializes
    the data from our form fields
    """

    __metaclass__ = models.SubfieldBase

    def __init__(self, *args, **kwargs):
        self.dump_kwargs = kwargs.pop('dump_kwargs',
                                      {'cls': DjangoJSONEncoder})
        self.load_kwargs = kwargs.pop('load_kwargs', {})

        super(JSONField, self).__init__(*args, **kwargs)

    def to_python(self, value):

        if isinstance(value, basestring):
            try:
                return json.loads(value, **self.load_kwargs)
            except ValueError:
                pass

        return value

    def get_db_prep_value(self, value, *args, **kwargs):

        if isinstance(value, basestring):
            return value

        return json.dumps(value, **self.dump_kwargs)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return self.get_db_prep_value(value)


class FormField(forms.MultiValueField):
    """The form field we can use in forms"""

    def __init__(self, form_class, related=None, **kwargs):
        self.form = form_class()
        self.myform = self.form
        # use this parameter if this field represents a relationship
        self.related = related
        # Set the widget and initial data
        kwargs['widget'] = FormFieldWidget(self.form.fields,self.form.media)
        kwargs['initial'] = [f.field.initial for f in self.form]

        super(FormField, self).__init__(**kwargs)
        self.fields = [f.field for f in self.form]

    def compress(self, data_list):
        """
        Return the cleaned_data of the form, everything should already be valid
        """
        data = {}
        if data_list:
            data = dict(
                (f.name, data_list[i]) for i, f in enumerate(self.form) if data_list[i])
            f = self.form.__class__(data)
            f.is_valid()
            return f.cleaned_data
        return data

    def clean(self, value):
        """
        Call the form is_valid to ensure every value supplied is valid
        """
        if not value and self.required:
            raise ValidationError(
                'Error found in Form Field: Nothing to validate')
        if not value:
            return

        #if we have an integer, assume that it is a foreignkey relationship.
        if(isinstance(value,int) and self.related):
            instance = self.related.objects.get(pk=value)
            if(issubclass(self.form.__class__,ModelForm)):
                form = self.form.__class__(instance.__dict__,instance=instance)
            else:
                # gather files 
                form = self.form.__class__(instance.__dict__)
        else:  
            data = dict((bf.name, value[i]) for i, bf in enumerate(self.form) if value[i])
            files = dict((k,v) for k, v in data.iteritems() if isinstance(v,UploadedFile))
            form = self.form.__class__(data,files=files)
       
        if not form.is_valid():
            error_dict = form.errors.items()
            errors = striptags(
                ", ".join(["%s (%s)" % (v, k) for k, v in error_dict]))

            raise ValidationError('Error(s) found: %s' % errors)
        elif self.related:
            form.save()
            return form.instance
        else:
            #return [ form.cleaned_data.get(f,None) for f in form.fields ]
            return form.cleaned_data

class ModelFormField(JSONField):
    """The json backed field we can use in our models"""

    def __init__(self, form, *args, **kwargs):
        """
        This field needs to be nullable and blankable. The supplied form
        will provide the validation.
        """
        self.form = form
        kwargs['null'] = True
        kwargs['blank'] = True

        super(ModelFormField, self).__init__(*args, **kwargs)

    def formfield(self, form_class=FormField, **kwargs):
        # Need to supply form to FormField
        return super(ModelFormField, self).formfield(form_class=form_class,
            form=self.form, **kwargs)

try:
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([], ["^formfield\.fields\.JSONField"])
    add_introspection_rules([], ["^formfield\.fields\.ModelFormField"])
except ImportError:
    pass
