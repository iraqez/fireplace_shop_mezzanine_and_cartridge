"""
Admin classes for all the shop models.

Many attributes in here are controlled by the ``SHOP_USE_VARIATIONS``
setting which defaults to True. In this case, variations are managed in
the product change view, and are created given the ``ProductOption``
values selected.

A handful of fields (mostly those defined on the abstract ``Priced``
model) are duplicated across both the ``Product`` and
``ProductVariation`` models, with the latter being the definitive
source, and the former supporting denormalised data that can be
referenced when iterating through products, without having to
query the underlying variations.

When ``SHOP_USE_VARIATIONS`` is set to False, a single variation is
still stored against each product, to keep consistent with the overall
model design. Since from a user perspective there are no variations,
the inlines for variations provide a single inline for managing the
one variation per product, so in the product change view, a single set
of price fields are available via the one variation inline.

Also when ``SHOP_USE_VARIATIONS`` is set to False, the denormalised
price fields on the product model are presented as editable fields in
the product change list - if these form fields are used, the values
are then pushed back onto the one variation for the product.
"""

from copy import deepcopy

from django.contrib import admin
from django.db.models import ImageField, ForeignKey
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext_lazy as _

from mezzanine.conf import settings
from mezzanine.core.admin import DisplayableAdmin, TabularDynamicInlineAdmin
from mezzanine.core.forms import OrderWidget
from mezzanine.pages.admin import PageAdmin
from mezzanine.utils.urls import admin_url

from cartridge.shop.fields import MoneyField
from cartridge.shop.forms import ProductAdminForm, ProductVariationAdminForm
from cartridge.shop.forms import ProductVariationAdminFormset
from cartridge.shop.forms import DiscountAdminForm, ImageWidget, MoneyWidget
from cartridge.shop.models import Category, Product, ProductImage
from cartridge.shop.models import ProductVariation, ProductOption, Order
from cartridge.shop.models import OrderItem, Sale, DiscountCode
from cartridge.shop.models import ProductTopka, ProductHearth, ProductPortal, ProductFacing, ProductStone

# Lists of field names.
option_fields = [f.name for f in ProductVariation.option_fields()]
_flds = lambda s: [f.name for f in Order._meta.fields if f.name.startswith(s)]
billing_fields = _flds("billing_detail")
shipping_fields = _flds("shipping_detail")


################
#  CATEGORIES  #
################

# Categories fieldsets are extended from Page fieldsets, since
# categories are a Mezzanine Page type.
category_fieldsets = deepcopy(PageAdmin.fieldsets)
category_fieldsets[0][1]["fields"][3:3] = ["content", "show_content", "products", "use_grouped_products"]
category_fieldsets += ((_("Product filters"), {
    "fields": ("sale", ("price_min", "price_max"), "combined"),
    "classes": ("collapse-closed",)},),)
if settings.SHOP_CATEGORY_USE_FEATURED_IMAGE:
    category_fieldsets[0][1]["fields"].insert(3, "featured_image")

# Options are only used when variations are in use, so only provide
# them as filters for dynamic categories when this is the case.
if settings.SHOP_USE_VARIATIONS:
    category_fieldsets[-1][1]["fields"] = (("options",) +
                                           category_fieldsets[-1][1]["fields"])


class CategoryAdmin(PageAdmin):
    fieldsets = category_fieldsets
    formfield_overrides = {ImageField: {"widget": ImageWidget}}
    filter_horizontal = ("options", "products",)

################
#  VARIATIONS  #
################

# If variations aren't used, the variation inline should always
# provide a single inline for managing the single variation per
# product.
variation_fields = ["sku", "num_in_stock", "unit_price", "currency",
                    "sale_price", "sale_from", "sale_to", "image"]
if settings.SHOP_USE_VARIATIONS:
    variation_fields.insert(1, "default")
    variations_max_num = None
    variations_extra = 0
else:
    variations_max_num = 1
    variations_extra = 1


class ProductVariationAdmin(admin.TabularInline):
    verbose_name_plural = _("Current variations")
    model = ProductVariation
    fields = variation_fields
    max_num = variations_max_num
    extra = variations_extra
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    form = ProductVariationAdminForm
    formset = ProductVariationAdminFormset
    ordering = ["option%s" % i for i in settings.SHOP_OPTION_ADMIN_ORDER]


class ProductImageAdmin(TabularDynamicInlineAdmin):
    model = ProductImage
    formfield_overrides = {ImageField: {"widget": ImageWidget}}

##############
#  PRODUCTS  #
##############

product_fieldsets = deepcopy(DisplayableAdmin.fieldsets)
product_fieldsets[0][1]["fields"].insert(2, "available")
product_fieldsets[0][1]["fields"].insert(3, "manufacturer")
product_fieldsets[0][1]["fields"].extend(["content", "categories"])
product_fieldsets = list(product_fieldsets)

other_product_fields = []
if settings.SHOP_USE_RELATED_PRODUCTS:
    other_product_fields.append("related_products")
if settings.SHOP_USE_UPSELL_PRODUCTS:
    other_product_fields.append("upsell_products")
if len(other_product_fields) > 0:
    product_fieldsets.append((_("Other products"), {
        "classes": ("collapse-closed",),
        "fields": tuple(other_product_fields)}))

product_list_display = ["admin_thumb", "title", "status", "available",
                        "admin_link"]
product_list_editable = ["status", "available"]

# If variations are used, set up the product option fields for managing
# variations. If not, expose the denormalised price fields for a product
# in the change list view.
if settings.SHOP_USE_VARIATIONS:
    product_fieldsets.insert(1, (_("Create new variations"),
                                 {"classes": ("create-variations",), "fields": option_fields}))
else:
    extra_list_fields = ["sku", "unit_price", "sale_price", "num_in_stock"]
    product_list_display[4:4] = extra_list_fields
    product_list_editable.extend(extra_list_fields)


class ProductAdmin(DisplayableAdmin):
    class Media:
        js = ("cartridge/js/admin/product_variations.js",)
        css = {"all": ("cartridge/css/admin/product.css",)}

    list_display = product_list_display
    list_display_links = ("admin_thumb", "title")
    list_editable = product_list_editable
    list_filter = ("status", "available", "categories", "content_model", "manufacturer")
    filter_horizontal = ("categories",) + tuple(other_product_fields)
    search_fields = ("title", "content", "categories__title",
                     "variations__sku")
    inlines = (ProductImageAdmin, ProductVariationAdmin)
    form = ProductAdminForm
    fieldsets = product_fieldsets

    def __init__(self, *args, **kwargs):
        """
        For ``Product`` subclasses that are registered with an Admin class
        that doesn't implement fieldsets, add any extra model fields
        to this instance's fieldsets. This mimics Django's behaviour of
        adding all model fields when no fieldsets are defined on the
        Admin class.
        """

        super(ProductAdmin, self).__init__(*args, **kwargs)

        # Test that the fieldsets don't differ from ProductAdmin's.
        if (self.model is not Product and
                    self.fieldsets == ProductAdmin.fieldsets):

            # Make a copy so that we aren't modifying other Admin
            # classes' fieldsets.
            self.fieldsets = deepcopy(self.fieldsets)

            # Insert each field between the publishing fields and nav
            # fields. Do so in reverse order to retain the order of
            # the model's fields.
            for field in reversed(self.model._meta.fields):
                check_fields = [f.name for f in Product._meta.fields]
                check_fields.append("product_ptr")
                try:
                    check_fields.extend(self.exclude)
                except (AttributeError, TypeError):
                    pass
                try:
                    check_fields.extend(self.form.Meta.exclude)
                except (AttributeError, TypeError):
                    pass
                if field.name not in check_fields and field.editable:
                    self.fieldsets[0][1]["fields"].insert(3, field.name)

    def save_model(self, request, obj, form, change):
        """
        Store the product object for creating variations in save_formset.
        """
        super(ProductAdmin, self).save_model(request, obj, form, change)
        self._product = obj

    def in_menu(self):
        """
        Hide subclasses from the admin menu.
        """
        return self.model is Product

    def save_formset(self, request, form, formset, change):
        """

        Here be dragons. We want to perform these steps sequentially:

        - Save variations formset
        - Run the required variation manager methods:
          (create_from_options, manage_empty, etc)
        - Save the images formset

        The variations formset needs to be saved first for the manager
        methods to have access to the correct variations. The images
        formset needs to be run last, because if images are deleted
        that are selected for variations, the variations formset will
        raise errors when saving due to invalid image selections. This
        gets addressed in the set_default_images method.

        An additional problem is the actual ordering of the inlines,
        which are in the reverse order for achieving the above. To
        address this, we store the images formset as an attribute, and
        then call save on it after the other required steps have
        occurred.

        """

        # Store the images formset for later saving, otherwise save the
        # formset.
        if formset.model == ProductImage:
            self._images_formset = formset
        else:
            super(ProductAdmin, self).save_formset(request, form, formset,
                                                   change)

        # Run each of the variation manager methods if we're saving
        # the variations formset.
        if formset.model == ProductVariation:
            # Build up selected options for new variations.
            options = dict([(f, request.POST.getlist(f)) for f in option_fields
                            if request.POST.getlist(f)])
            # Create a list of image IDs that have been marked to delete.
            deleted_images = [request.POST.get(f.replace("-DELETE", "-id"))
                              for f in request.POST if f.startswith("images-")
                and f.endswith("-DELETE")]

            # Create new variations for selected options.
            self._product.variations.create_from_options(options)
            # Create a default variation if there are none.
            self._product.variations.manage_empty()

            # Remove any images deleted just now from variations they're
            # assigned to, and set an image for any variations without one.
            self._product.variations.set_default_images(deleted_images)

            # Save the images formset stored previously.
            super(ProductAdmin, self).save_formset(request, form,
                                                   self._images_formset, change)

            # Run again to allow for no images existing previously, with
            # new images added which can be used as defaults for variations.
            self._product.variations.set_default_images(deleted_images)

            # Copy duplicate fields (``Priced`` fields) from the default
            # variation to the product.
            self._product.copy_default_variation()

    def change_view(self, request, object_id, extra_context=None):
        """
        As in Mezzanine's ``Page`` model, check ``product.get_content_model()``
        for a subclass and redirect to its admin change view.
        """
        if self.model is Product:
            product = get_object_or_404(Product, pk=object_id)
            content_model = product.get_content_model()
            if content_model is not None:
                change_url = admin_url(content_model.__class__, "change",
                                       content_model.id)
                return HttpResponseRedirect(change_url)
        return super(ProductAdmin, self).change_view(request, object_id,
                                                     extra_context=extra_context)


class ProductOptionAdmin(admin.ModelAdmin):
    ordering = ("type", "name")
    list_display = ("type", "name")
    list_display_links = ("type",)
    list_editable = ("name",)
    list_filter = ("type",)
    search_fields = ("type", "name")
    radio_fields = {"type": admin.HORIZONTAL}


class OrderItemInline(admin.TabularInline):
    verbose_name_plural = _("Items")
    model = OrderItem
    extra = 0
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}


def address_pairs(fields):
    """
    Zips address fields into pairs, appending the last field if the
    total is an odd number.
    """
    pairs = list(zip(fields[::2], fields[1::2]))
    if len(fields) % 2:
        pairs.append(fields[-1])
    return pairs


class OrderAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("cartridge/css/admin/order.css",)}

    ordering = ("status", "-id")
    list_display = ("id", "billing_name", "total", "time", "status", "invoice")
    list_editable = ("status",)
    list_filter = ("status", "time")
    list_display_links = ("id", "billing_name",)
    search_fields = (["id", "status"] +
                     billing_fields + shipping_fields)
    date_hierarchy = "time"
    radio_fields = {"status": admin.HORIZONTAL}
    inlines = (OrderItemInline,)
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    fieldsets = (
        (_("Billing details"), {"fields": address_pairs(billing_fields)}),
        (_("Shipping details"), {"fields": address_pairs(shipping_fields)}),
        (None, {"fields": ("additional_instructions", ("shipping_total",
                                                       "shipping_type"),
                           ("discount_total", "discount_code"), "item_total",
                           ("total", "status"))}),
    )


class SaleAdmin(admin.ModelAdmin):
    list_display = ("title", "active", "discount_deduct", "discount_percent",
                    "discount_exact", "valid_from", "valid_to")
    list_editable = ("active", "discount_deduct", "discount_percent",
                     "discount_exact", "valid_from", "valid_to")
    filter_horizontal = ("categories", "products")
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    form = DiscountAdminForm
    fieldsets = (
        (None, {"fields": ("title", "active")}),
        (_("Apply to product and/or products in categories"),
         {"fields": ("products", "categories")}),
        (_("Reduce unit price by"),
         {"fields": (("discount_deduct", "discount_percent",
                      "discount_exact"),)}),
        (_("Sale period"), {"fields": (("valid_from", "valid_to"),)}),
    )


class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ("title", "active", "code", "discount_deduct",
                    "discount_percent", "min_purchase", "free_shipping", "valid_from",
                    "valid_to")
    list_editable = ("active", "code", "discount_deduct", "discount_percent",
                     "min_purchase", "free_shipping", "valid_from", "valid_to")
    filter_horizontal = ("categories", "products")
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    form = DiscountAdminForm
    fieldsets = (
        (None, {"fields": ("title", "active", "code")}),
        (_("Apply to product and/or products in categories"),
         {"fields": ("products", "categories")}),
        (_("Reduce unit price by"),
         {"fields": (("discount_deduct", "discount_percent"),)}),
        (None, {"fields": (("min_purchase", "free_shipping"),)}),
        (_("Valid for"),
         {"fields": (("valid_from", "valid_to", "uses_remaining"),)}),
    )


portal_fieldsets = deepcopy(ProductAdmin.fieldsets)
portal_fieldsets[0][1]["fields"][3:3] = ["overall_height",
                                         "overall_width",
                                         "overall_depth",
                                         "materials",
                                         "suitable_topka",
                                         "suitable_hearth"]


class ProductPortalAdmin(ProductAdmin):
    fieldsets = portal_fieldsets
    filter_horizontal = tuple(deepcopy(ProductAdmin.filter_horizontal)) + ("suitable_topka", "suitable_hearth",)


facing_fieldsets = deepcopy(ProductAdmin.fieldsets)
facing_fieldsets[0][1]["fields"][3:3] = ["overall_height",
                                         "overall_width",
                                         "overall_depth",
                                         "materials",
                                         "mass",
                                         "type",
                                         "suitable_hearth",
                                         "suitable_topka"]


class ProductFacingAdmin(ProductAdmin):
    fieldsets = facing_fieldsets
    filter_horizontal = tuple(deepcopy(ProductAdmin.filter_horizontal)) + ("suitable_hearth", "suitable_topka")


hearth_fieldsets = deepcopy(ProductAdmin.fieldsets)
hearth_fieldsets[0][1]["fields"][3:3] = ["power",
                                         "overall_height", "overall_width", "overall_depth",
                                         "inst_height", "inst_width", "inst_depth",
                                         "type",
                                         "rc",
                                         "heating",
                                         "suitable_portals",
                                         "suitable_faces"]


class ProductHearthAdmin(ProductAdmin):
    fieldsets = hearth_fieldsets
    filter_horizontal = tuple(deepcopy(ProductAdmin.filter_horizontal)) + ("suitable_portals", "suitable_faces",)


topka_fieldsets = deepcopy(ProductAdmin.fieldsets)
topka_fieldsets[0][1]["fields"][3:3] = ["power",
                                        "mass",
                                        "diam",
                                        "height", "width", "depth",
                                        "performance",
                                        "fuel",
                                        "water",
                                        "lift",
                                        "shutter",
                                        "glass",
                                        "suitable_portals",
                                        "suitable_faces"]


class ProductTopkaAdmin(ProductAdmin):
    fieldsets = topka_fieldsets
    filter_horizontal = tuple(deepcopy(ProductAdmin.filter_horizontal)) + ("suitable_portals", "suitable_faces")


admin.site.register(Category, CategoryAdmin)
admin.site.register(Product, ProductAdmin)
if settings.SHOP_USE_VARIATIONS:
    admin.site.register(ProductOption, ProductOptionAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(Sale, SaleAdmin)
admin.site.register(DiscountCode, DiscountCodeAdmin)

admin.site.register(ProductTopka, ProductTopkaAdmin)
admin.site.register(ProductHearth, ProductHearthAdmin)
admin.site.register(ProductPortal, ProductPortalAdmin)
admin.site.register(ProductFacing, ProductFacingAdmin)
admin.site.register(ProductStone, ProductAdmin)

