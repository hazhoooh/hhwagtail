from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from wagtail.core.models import Page

def set_page_position(request, page_to_move_id, position):
    page_to_move = get_object_or_404(Page, id=page_to_move_id)
    parent_page = page_to_move.get_parent()
    if not parent_page.permissions_for_user(request.user).can_reorder_children():raise PermissionDenied
    if request.method == 'POST':
        page_in_wanted_position = None
        page_in_wanted_position = parent_page.get_children()[position]
        
        # Move page 
        if page_in_wanted_position and page_in_wanted_position != page_to_move: # Check if the pages are different
            old_position = list(parent_page.get_children()).index(page_to_move)
            if position < old_position: page_to_move.move(page_in_wanted_position, pos='left', user=request.user)
            elif position > old_position: page_to_move.move(page_in_wanted_position, pos='right', user=request.user)
        else: page_to_move.move(parent_page, pos='last-child', user=request.user) # Move page to end

    return HttpResponse(f"{{'position':{position},'page_to_move':{page_to_move},'parent_page':{parent_page},'page_in_wanted_position':{page_in_wanted_position}}}")
