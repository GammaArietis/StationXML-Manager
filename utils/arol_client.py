import os
import yaml
import json
import logging
from core.models.base_models import Sensor, Datalogger, PoleZero, ResponseFilter

logger = logging.getLogger(__name__)

class AROLClient:
    def __init__(self, library_path=None):
        if library_path is None:
            base_dir = os.path.dirname(__file__)
            self.library_path = os.path.join(base_dir, 'AROL_Library', 'objects')
        else:
            self.library_path = library_path
            
        if not os.path.exists(self.library_path):
            logger.error("AROL library not found: %s", self.library_path)
    
    def _clean_model_name(self, name):
        """Removes technical suffixes and transforms .100 into _100HZ."""
        import re
        n = name.upper()
        
        # 1. Remove known extensions
        for suffix in ['.RESPONSE', '.FILTER', '.COEFF', '.TEMP', '.POLY', '.YAML']:
            n = n.replace(suffix, '')
        
        # 2. Transform the final dot into HZ (e.g.: .100 -> _100HZ)
        # Looks for a dot followed by numbers at the end of the string
        n = re.sub(r'\.(\d+)$', r'_\1HZ', n)
        
        return n.strip().replace('..', '.')
    
    def _parse_complex(self, value):
        """Converts both dictionaries (NRL style) and strings (AROL style) into PoleZero."""
        try:
            # 1. If the data is a dictionary (Classic for OTHER and HALLIBURTON)
            if isinstance(value, dict):
                r = float(value.get('real', 0.0) or 0.0)
                i = float(value.get('imag', 0.0) or 0.0)
                return PoleZero(r, i)
            
            # 2. If it's a simple pure number (e.g., an integer or float without 'j')
            elif isinstance(value, (int, float)):
                return PoleZero(float(value), 0.0)
                
            # 3. If it's a complex string (Modern format Nanometrics/EPOS)
            else:
                c_val = complex(str(value).replace(' ', ''))
                return PoleZero(float(c_val.real), float(c_val.imag))
                
        except Exception as e:
            logger.warning(f"Complex parsing error '{value}': {e}")
            return PoleZero(0.0, 0.0)

    def _resolve_ref(self, ref_path, category, manufacturer):
        """Follows the $ref link looking for the include/ folder or the file intelligently (Radar)."""
        relative_file = ref_path.split('#')[0]
        base_name = os.path.basename(relative_file)
        
        # Find the exact category folder
        cat_folder = category
        for c in [category, category + 's', 'Sensors', 'Sensor', 'Dataloggers', 'Datalogger']:
            if os.path.exists(os.path.join(self.library_path, c)):
                cat_folder = c
                break
                
        mfg_path = os.path.join(self.library_path, cat_folder, manufacturer)
        
        # THE RADAR: List of all possible locations
        candidate_paths = [
            os.path.abspath(os.path.join(mfg_path, relative_file)), # 1. Exactly where the file says
            os.path.abspath(os.path.join(mfg_path, 'include', base_name)), # 2. In the manufacturer's include/ folder
            os.path.abspath(os.path.join(mfg_path, base_name)), # 3. Dumped in the manufacturer's root
            os.path.abspath(os.path.join(self.library_path, 'include', base_name)) # 4. In a global include/ folder
        ]
        
        full_path = None
        for p in candidate_paths:
            if os.path.exists(p):
                full_path = p
                break
                
        if not full_path:
            logger.error("[AROL] Unable to find referenced file: %s", base_name)
            return {}
            
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f)
                filter_data = content.get('filter', {})
                if 'extras' in content:
                    filter_data['_extras'] = content['extras']
                return filter_data
        except Exception as e:
            logger.exception("Error loading AROL $ref %s: %s", ref_path, e)
            return {}
            
    def get_manufacturers(self, category='Sensors'):
        cat_path = os.path.join(self.library_path, category)
        if not os.path.exists(cat_path): return []
        return sorted([d for d in os.listdir(cat_path) if os.path.isdir(os.path.join(cat_path, d))])

    def get_models(self, category, manufacturer):
        mfg_path = os.path.join(self.library_path, category, manufacturer)
        if not os.path.exists(mfg_path): return []
        return sorted([f.replace('.yaml', '') for f in os.listdir(mfg_path) if f.endswith('.yaml')])

    def load_component(self, category, manufacturer, model_name):
        cat_folder = category
        for c in [category, category + 's', 'Sensors', 'Sensor', 'Dataloggers', 'Datalogger']:
            if os.path.exists(os.path.join(self.library_path, c)):
                cat_folder = c
                break

        file_path = os.path.join(self.library_path, cat_folder, manufacturer, f"{model_name}.yaml")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            # Direct traffic to the correct function
            if 'sensor' in category.lower():
                return self._map_to_sensor(data, manufacturer, model_name, cat_folder)
            elif 'datalogger' in category.lower():
                return self._map_to_datalogger(data, manufacturer, model_name, cat_folder)
            return None
        except Exception as e:
            logger.exception("Error loading AROL component %s/%s: %s", manufacturer, model_name, e)
            return None

    def _map_to_sensor(self, data, mfg, model, category):
        resp = data.get('response', {})
        stages = resp.get('stages', [])
        
        sens = 1.0; freq = 1.0; in_u = "m/s"; out_u = "V"
        paz_data = {}

        if stages:
            s1 = stages[0]
            gain = s1.get('gain', {})
            sens = gain.get('value', 1.0)
            freq = gain.get('frequency', 1.0)
            in_u = s1.get('input_units', {}).get('name', 'm/s')
            out_u = s1.get('output_units', {}).get('name', 'V')
            
            f_node = s1.get('filter', {})
            if isinstance(f_node, dict) and '$ref' in f_node:
                paz_data = self._resolve_ref(f_node['$ref'], category, mfg)
            else:
                paz_data = f_node
        
        extras = paz_data.get('_extras', {})
        a0 = extras.get('Transfer_normalization_constant', 1.0)
        f0 = extras.get('Transfer_normalization_frequency', 1.0)

        units = str(paz_data.get('units', '')).upper()
        pz_type = "LAPLACE (HERTZ)" if "HZ" in units else "LAPLACE (RADIANS/SECOND)"

        return Sensor(
            manufacturer=mfg.upper(),
            model=self._clean_model_name(model.upper()),
            type="SENSOR",
            description=data.get('description', 'Imported from AROL'),
            sensitivity=float(sens),
            frequency=float(freq),
            input_units=in_u,
            output_units=out_u,
            normalization_factor=float(a0),
            normalization_freq=float(f0),
            pz_transfer_function_type=pz_type,
            zeros=[self._parse_complex(z) for z in paz_data.get('zeros', [])],
            poles=[self._parse_complex(p) for p in paz_data.get('poles', [])]
        )

    def _map_to_datalogger(self, data, mfg, model, category):
        resp = data.get('response', {})
        stages = resp.get('stages', [])
        
        filters = []
        total_gain = resp.get('total_gain', 1.0)
        
        for idx, stage in enumerate(stages):
            f_node = stage.get('filter', {})
            filter_data = {}
            if isinstance(f_node, dict) and '$ref' in f_node:
                filter_data = self._resolve_ref(f_node['$ref'], category, mfg)
            else:
                filter_data = f_node
            
            f_type = filter_data.get('type', stage.get('type', 'UNKNOWN')).upper()
            stage_gain = stage.get('gain', {}).get('value', 1.0)
            
            payload = {
                "type": f_type,
                "data": filter_data,
                "description": stage.get('name', f"Stage {idx+1}"),
                "stage_gain": stage_gain
            }
            
            dec_delay = stage.get('delay', 0.0) or 0.0
            dec_corr = stage.get('correction', 0.0) or 0.0
            
            filters.append(ResponseFilter(
                stage_number=idx + 1,
                filter_type=f_type,
                coefficients=json.dumps(payload),
                decimation_factor=stage.get('decimation_factor', 1),
                input_sample_rate=stage.get('input_sample_rate', 0.0),
                output_sample_rate=stage.get('output_sample_rate', 0.0),
                estimated_delay=float(dec_delay),      
                correction_applied=float(dec_corr)
            ))
            
        return Datalogger(
            manufacturer=mfg.upper(),
            model=self._clean_model_name(model.upper()),
            description=data.get('description', 'Imported from AROL'),
            gain=float(total_gain),
            filters=filters
        )