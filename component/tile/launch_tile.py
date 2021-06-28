import time 
from functools import partial

from sepal_ui import sepalwidgets as sw
from sepal_ui import color as sc
from sepal_ui.scripts import utils as su
import ipyvuetify as v
import ee

from component.message import cm
from component import scripts as cs
from component import parameter as cp

ee.Initialize()

class LaunchTile(sw.Tile):
    
    def __init__(self, aoi_tile, model, result_tile):
        
        # gather the model objects 
        self.aoi_model = aoi_tile.view.model 
        self.model = model 
        
        # add the result_tile map to attributes 
        self.m = result_tile.m
        self.tile = result_tile
        
        # create the widgets 
        mkd = sw.Markdown(cm.process_txt)
        
        # create the tile 
        super().__init__(
            'compute_widget',
            cm.tile.launch,
            inputs = [mkd],
            btn = sw.Btn(cm.launch_btn, class_='mt-5'),
            alert = sw.Alert()
        )
        
        # link the js behaviours
        self.btn.on_event('click', self._launch_fcdm)
        aoi_tile.view.observe(self._update_geometry, 'updated')
        
    def _update_geometry(self, change):
        """update the map widget geometry"""
        
        self.tile.save.geometry = self.aoi_model.feature_collection.geometry()
        
        return self
    
    @su.loading_button(debug=False)
    def _launch_fcdm(self, widget, event, data):
        
        # test all the values
        if not self.alert.check_input(self.aoi_model.name, cm.missing_input): return
        for k, val in self.model.export_data().items():
            if not ('forest_mask' in k or self.alert.check_input(val, cm.missing_input.format(k))): return
        
        # display the aoi 
        self.m.addLayer(self.aoi_model.feature_collection, {'color': sc.info}, 'aoi')
        self.m.zoom_ee_object(self.aoi_model.feature_collection.geometry())
        
        # display the forest mask 
        self.model.forest_mask, self.model.forest_mask_display = cs.get_forest_mask(
            self.model.forest_map, 
            self.model.forest_map_year, 
            self.model.treecover, 
            self.aoi_model.feature_collection
        )
        self.m.addLayer(
            self.model.forest_mask_display, 
            cp.viz_forest_mask[self.model.forest_map], 
            'Forest mask'
        )
        
        # remove all already existing fcdm layers 
        for layer in self.m.layers:
            if not layer.name in ['aoi', 'Forest mask', 'CartoDB.DarkMatter']:
                self.m.remove_layer(layer)
        
        # compute nbr 
        analysis_nbr_merge = ee.ImageCollection([])
        reference_nbr_merge = ee.ImageCollection([])
        for sensor in self.model.sensors:
    
            # analysis period
            # data preparation
            # Calculation of single scenes of Base-NBR
            analysis = cs.get_collection(
                sensor, 
                self.model.analysis_start, 
                self.model.analysis_end, 
                self.model.forest_map, 
                self.model.forest_map_year, 
                self.model.forest_mask, 
                self.model.cloud_buffer,
                self.aoi_model.feature_collection
            )
            analysis_nbr = analysis.map(partial(cs.compute_nbr, sensor=sensor))

            # analysis period
            # data preparation
            # Calculation of single scenes of Base-NBR
            reference = cs.get_collection(
                sensor, 
                self.model.reference_start, 
                self.model.reference_end, 
                self.model.forest_map, 
                self.model.forest_map_year, 
                self.model.forest_mask, 
                self.model.cloud_buffer,
                self.aoi_model.feature_collection
            )
            reference_nbr = reference.map(partial(cs.compute_nbr, sensor=sensor))
            
            # adjust with kernel
            reference_nbr = reference_nbr.map(partial(cs.adjustment_kernel, kernel_size = self.model.kernel_radius))
            analysis_nbr = analysis_nbr.map(partial(cs.adjustment_kernel, kernel_size = self.model.kernel_radius)) 

            analysis_nbr_merge = analysis_nbr_merge.merge(analysis_nbr)
            reference_nbr_merge = reference_nbr_merge.merge(reference_nbr)
    
        # Capping of self-referenced single Second-NBR scenes at 0 and -1
        # Condensation of all available self-referenced single Second-NBR scenes per investigation period
        analysis_nbr_norm_min = analysis_nbr_merge \
            .map(cs.capping) \
            .qualityMosaic('NBR')

        reference_nbr_norm_min = reference_nbr_merge \
            .map(cs.capping) \
            .qualityMosaic('NBR')
        
        # save the differents layer to download
        datasets = {'forest mask': self.model.forest_mask}
        datasets['NBR_reference'] = reference_nbr_norm_min.select('NBR', 'yearday')
        datasets['NBR_analysis'] = analysis_nbr_norm_min.select('NBR', 'yearday')
            
        # Derive the Delta-NBR result
        nbr_diff = analysis_nbr_norm_min.select('NBR').subtract(reference_nbr_norm_min.select('NBR'))
        nbr_diff_capped = nbr_diff.select('NBR').where(nbr_diff.select('NBR').lt(0), 0)
        datasets['NBR_diff'] = nbr_diff_capped.select('NBR')            

        # Display of condensed Second-NBR scene and information about the acquisition dates of the second satellite data per single pixel location
        #self.m.addLayer(analysis_nbr_norm_min.select('NBR'),{'min':[0],'max':[0.3],'palette':'D3D3D3,Ce0f0f'},'rNBR-Analysis')
        #self.m.addLayer(analysis_nbr_norm_min.select('yearday'),{'min': self.model.yearday_a_s(), 'max': self.model.yearday_a_e(), 'palette': 'ff0000,ffffff'},'Date rNBR-Analysis')
        
        # Display of condensed Base-NBR scene and information about the acquisition dates of the base satellite data per single pixel location
        #self.m.addLayer(reference_nbr_norm_min.select('NBR'),{'min':[0],'max':[0.3],'palette':'D3D3D3,Ce0f0f'},'rNBR-Reference')
        #self.m.addLayer(reference_nbr_norm_min.select('yearday'),{'min': self.model.yearday_r_s(), 'max': self.model.yearday_r_e() ,'palette': 'ff0000,ffffff'},'Date rNBR-Reference')
        
        self.m.addLayer (nbr_diff_capped.select('NBR'),{'min':[0],'max':[0.3],'palette':'D3D3D3,Ce0f0f'},'Delta-rNBR')
            
        # add the selected datasets to the export control 
        self.tile.save.set_data(datasets)
        self.tile.save.set_prefix(
            self.model.reference_start[:4], 
            self.model.reference_end[:4], 
            self.model.analysis_start[:4], 
            self.model.analysis_end[:4], 
            self.aoi_model.name
        )
            
        self.alert.add_live_msg(cm.complete, 'success')
        
        return
        
        